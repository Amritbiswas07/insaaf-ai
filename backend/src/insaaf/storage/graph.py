"""Neo4j: the legal knowledge graph *and* the retrieval index.

Graph model
-----------
(:Case {id, title, court, date, year, url, summary, holding, outcome, case_type,
        issues, principles, cited_by_count, indexed})
(:Judge {id, name})          -[:AUTHORED]->(:Case), -[:ON_BENCH]->(:Case)
(:Court {name})              <-[:DECIDED_IN]-(:Case)
(:Party {id, name})          -[:PARTY_TO {role}]->(:Case)
(:Act {id, name})            <-[:OF_ACT]-(:Section {id, act, number, label})
(:Case)-[:REFERENCES {mentions}]->(:Section)
(:Case)-[:CITES {mentions}]->(:Case)        # target may be a stub not yet ingested
(:Case)-[:HAS_CHUNK]->(:Chunk {id, case_id, idx, text, roles, embedding})

Chunks carry a vector index (semantic search) and a full-text index (exact
legal terms such as "Section 438" or party names), fused at query time.
"""

from __future__ import annotations

import re
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase, NotificationDisabledClassification

from insaaf.domain import CaseInsights, Chunk, Judgment, StatuteRef

VECTOR_INDEX = "chunk_embedding"
FULLTEXT_INDEX = "chunk_text"
CASE_TITLE_INDEX = "case_title"

_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def lucene_escape(q: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", q)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class GraphStore:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        # Neo4j 2025+ flags the index procedures as deprecated in favour of SEARCH;
        # we keep them so the same queries run on Neo4j 5.x.
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(
            uri,
            auth=(user, password),
            notifications_disabled_classifications=[NotificationDisabledClassification.DEPRECATION],
        )
        self._db = database

    async def close(self) -> None:
        await self._driver.close()

    async def ping(self) -> bool:
        await self._driver.verify_connectivity()
        return True

    async def _read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        records, _, _ = await self._driver.execute_query(
            query, params, database_=self._db, routing_="r"
        )
        return [r.data() for r in records]

    async def _write(self, query: str, **params: Any) -> None:
        await self._driver.execute_query(query, params, database_=self._db)

    # ------------------------------------------------------------- schema

    async def ensure_schema(self, embed_dim: int) -> None:
        stmts = [
            "CREATE CONSTRAINT case_id IF NOT EXISTS FOR (n:Case) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT judge_id IF NOT EXISTS FOR (n:Judge) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT court_name IF NOT EXISTS FOR (n:Court) REQUIRE n.name IS UNIQUE",
            "CREATE CONSTRAINT party_id IF NOT EXISTS FOR (n:Party) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT act_id IF NOT EXISTS FOR (n:Act) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT section_id IF NOT EXISTS FOR (n:Section) REQUIRE n.id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
            "CREATE INDEX case_year IF NOT EXISTS FOR (n:Case) ON (n.year)",
            f"CREATE FULLTEXT INDEX {FULLTEXT_INDEX} IF NOT EXISTS FOR (n:Chunk) ON EACH [n.text]",
            f"CREATE FULLTEXT INDEX {CASE_TITLE_INDEX} IF NOT EXISTS FOR (n:Case) ON EACH [n.title, n.summary]",
            (
                f"CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (n:Chunk) ON (n.embedding) "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {int(embed_dim)}, "
                "`vector.similarity_function`: 'cosine'}}"
            ),
        ]
        for stmt in stmts:
            await self._write(stmt)

    # ------------------------------------------------------------- writes

    async def upsert_case(
        self,
        j: Judgment,
        insights: CaseInsights | None,
        statutes: list[tuple[StatuteRef, int]],
        cited_case_ids: list[tuple[str, int]],
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        case = {
            "id": j.doc_id,
            "title": j.title,
            "court": j.court,
            "date": j.decision_date.isoformat() if j.decision_date else None,
            "year": j.year,
            "url": j.url,
            "cited_by_count": j.cited_by_count or 0,
            "summary": insights.summary if insights else None,
            "holding": insights.holding if insights else None,
            "outcome": insights.outcome.value if insights else None,
            "case_type": insights.case_type if insights else None,
            "issues": insights.legal_issues if insights else [],
            "principles": insights.key_principles if insights else [],
        }
        judges = [{"id": slug(n), "name": n, "author": slug(n) == slug(j.author or "")} for n in j.bench]
        if j.author and slug(j.author) not in {x["id"] for x in judges}:
            judges.append({"id": slug(j.author), "name": j.author, "author": True})
        parties = [{"id": slug(p.name), "name": p.name, "role": p.role} for p in j.parties]
        sections = [
            {
                "id": ref.key,
                "act": ref.act,
                "act_name": ref.act_full_name or ref.act,
                "number": ref.section,
                "label": ref.label,
                "mentions": n,
            }
            for ref, n in statutes
            if ref.section
        ]
        cites = [{"id": cid, "mentions": n} for cid, n in cited_case_ids if cid != j.doc_id]
        chunk_rows = [
            {
                "id": c.chunk_id,
                "idx": c.idx,
                "text": c.text,
                "roles": [r.value for r in c.roles],
                "para_start": c.para_start,
                "para_end": c.para_end,
                "embedding": emb,
            }
            for c, emb in zip(chunks, embeddings, strict=True)
        ]

        async def tx_fn(tx: Any) -> None:
            await tx.run(
                """
                MERGE (c:Case {id: $case.id})
                SET c += $case, c.indexed = true
                WITH c
                OPTIONAL MATCH (c)-[r:AUTHORED|ON_BENCH|PARTY_TO|REFERENCES|CITES|DECIDED_IN]-()
                WHERE startNode(r) = c OR type(r) IN ['AUTHORED','ON_BENCH','PARTY_TO']
                DELETE r
                WITH DISTINCT c
                OPTIONAL MATCH (c)-[:HAS_CHUNK]->(old:Chunk)
                DETACH DELETE old
                """,
                case=case,
            )
            if j.court:
                await tx.run(
                    "MATCH (c:Case {id: $id}) MERGE (ct:Court {name: $court}) MERGE (c)-[:DECIDED_IN]->(ct)",
                    id=j.doc_id,
                    court=j.court,
                )
            await tx.run(
                """
                MATCH (c:Case {id: $id})
                UNWIND $judges AS jd
                MERGE (jg:Judge {id: jd.id}) ON CREATE SET jg.name = jd.name
                MERGE (jg)-[:ON_BENCH]->(c)
                FOREACH (_ IN CASE WHEN jd.author THEN [1] ELSE [] END | MERGE (jg)-[:AUTHORED]->(c))
                """,
                id=j.doc_id,
                judges=judges,
            )
            await tx.run(
                """
                MATCH (c:Case {id: $id})
                UNWIND $parties AS p
                MERGE (pt:Party {id: p.id}) ON CREATE SET pt.name = p.name
                MERGE (pt)-[r:PARTY_TO {role: p.role}]->(c)
                """,
                id=j.doc_id,
                parties=parties,
            )
            await tx.run(
                """
                MATCH (c:Case {id: $id})
                UNWIND $sections AS s
                MERGE (a:Act {id: s.act}) ON CREATE SET a.name = s.act_name
                MERGE (sec:Section {id: s.id})
                  ON CREATE SET sec.act = s.act, sec.number = s.number, sec.label = s.label
                MERGE (sec)-[:OF_ACT]->(a)
                MERGE (c)-[r:REFERENCES]->(sec) SET r.mentions = s.mentions
                """,
                id=j.doc_id,
                sections=sections,
            )
            await tx.run(
                """
                MATCH (c:Case {id: $id})
                UNWIND $cites AS ct
                MERGE (t:Case {id: ct.id})
                  ON CREATE SET t.indexed = false, t.url = $base + ct.id + '/'
                MERGE (c)-[r:CITES]->(t) SET r.mentions = ct.mentions
                """,
                id=j.doc_id,
                cites=cites,
                base=j.url.rsplit("/doc/", 1)[0] + "/doc/",
            )
            await tx.run(
                """
                MATCH (c:Case {id: $id})
                UNWIND $chunks AS ch
                CREATE (k:Chunk {id: ch.id, case_id: $id, idx: ch.idx, text: ch.text,
                                 roles: ch.roles, para_start: ch.para_start, para_end: ch.para_end})
                WITH c, k, ch
                CALL db.create.setNodeVectorProperty(k, 'embedding', ch.embedding)
                CREATE (c)-[:HAS_CHUNK]->(k)
                """,
                id=j.doc_id,
                chunks=chunk_rows,
            )

        async with self._driver.session(database=self._db) as session:
            await session.execute_write(tx_fn)

    # ------------------------------------------------------------- retrieval

    async def vector_search(self, embedding: list[float], k: int) -> list[dict[str, Any]]:
        return await self._read(
            f"""
            CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $k, $vec) YIELD node, score
            RETURN node.id AS chunk_id, node.case_id AS case_id, node.text AS text,
                   node.roles AS roles, score
            """,
            k=k,
            vec=embedding,
        )

    async def fulltext_search(self, query: str, k: int) -> list[dict[str, Any]]:
        q = lucene_escape(query.strip())
        if not q:
            return []
        return await self._read(
            f"""
            CALL db.index.fulltext.queryNodes('{FULLTEXT_INDEX}', $q, {{limit: $k}}) YIELD node, score
            RETURN node.id AS chunk_id, node.case_id AS case_id, node.text AS text,
                   node.roles AS roles, score
            """,
            q=q,
            k=k,
        )

    async def cases_meta(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        rows = await self._read(
            """
            MATCH (c:Case) WHERE c.id IN $ids
            OPTIONAL MATCH (c)-[:REFERENCES]->(s:Section)
            WITH c, collect(DISTINCT s.label)[..12] AS statutes
            RETURN c.id AS id, c.title AS title, c.court AS court, c.date AS date, c.year AS year,
                   c.url AS url, c.summary AS summary, c.holding AS holding, c.outcome AS outcome,
                   c.cited_by_count AS cited_by_count, statutes
            """,
            ids=ids,
        )
        return {r["id"]: r for r in rows}

    async def co_cited_precedents(self, case_ids: list[str], min_support: int = 2, limit: int = 5) -> list[dict[str, Any]]:
        """Precedents cited by several of the retrieved cases — a strong graph signal
        that the precedent is the leading authority on the question."""
        return await self._read(
            """
            MATCH (c:Case)-[:CITES]->(p:Case)
            WHERE c.id IN $ids AND NOT p.id IN $ids
            WITH p, count(DISTINCT c) AS support
            WHERE support >= $min_support
            RETURN p.id AS id, p.title AS title, p.court AS court, p.date AS date, p.url AS url,
                   p.summary AS summary, support
            ORDER BY support DESC, p.cited_by_count DESC LIMIT $limit
            """,
            ids=case_ids,
            min_support=min_support,
            limit=limit,
        )

    async def related_cases(self, case_id: str, relation: str, limit: int = 10) -> list[dict[str, Any]]:
        queries = {
            "cites": """
                MATCH (:Case {id: $id})-[r:CITES]->(p:Case)
                RETURN p.id AS id, p.title AS title, p.court AS court, p.date AS date, p.url AS url,
                       p.summary AS summary, r.mentions AS weight
                ORDER BY r.mentions DESC, p.cited_by_count DESC LIMIT $limit""",
            "cited_by": """
                MATCH (p:Case)-[:CITES]->(:Case {id: $id})
                RETURN p.id AS id, p.title AS title, p.court AS court, p.date AS date, p.url AS url,
                       p.summary AS summary, p.cited_by_count AS weight
                ORDER BY p.date DESC LIMIT $limit""",
            "shares_statutes": """
                MATCH (:Case {id: $id})-[:REFERENCES]->(s:Section)<-[:REFERENCES]-(p:Case)
                WITH p, collect(s.label) AS shared
                RETURN p.id AS id, p.title AS title, p.court AS court, p.date AS date, p.url AS url,
                       p.summary AS summary, size(shared) AS weight, shared
                ORDER BY weight DESC, p.cited_by_count DESC LIMIT $limit""",
            "same_bench": """
                MATCH (:Case {id: $id})<-[:ON_BENCH]-(j:Judge)-[:ON_BENCH]->(p:Case)
                WITH p, collect(j.name) AS judges
                RETURN p.id AS id, p.title AS title, p.court AS court, p.date AS date, p.url AS url,
                       p.summary AS summary, size(judges) AS weight, judges
                ORDER BY p.date DESC LIMIT $limit""",
        }
        if relation not in queries:
            raise ValueError(f"unknown relation {relation!r}; expected one of {sorted(queries)}")
        return await self._read(queries[relation], id=case_id, limit=limit)

    async def cases_for_section(self, act: str, section: str | None, limit: int = 15) -> list[dict[str, Any]]:
        return await self._read(
            """
            MATCH (c:Case)-[r:REFERENCES]->(s:Section)-[:OF_ACT]->(a:Act {id: $act})
            WHERE $section IS NULL OR s.number = $section
            RETURN c.id AS id, c.title AS title, c.court AS court, c.date AS date, c.url AS url,
                   c.summary AS summary, c.outcome AS outcome, s.label AS section, r.mentions AS mentions
            ORDER BY r.mentions DESC, c.cited_by_count DESC LIMIT $limit
            """,
            act=act,
            section=section,
            limit=limit,
        )

    async def case_graph(self, case_id: str) -> dict[str, Any]:
        rows = await self._read(
            """
            MATCH (c:Case {id: $id})
            OPTIONAL MATCH (j:Judge)-[:ON_BENCH]->(c)
            OPTIONAL MATCH (c)-[:REFERENCES]->(s:Section)
            OPTIONAL MATCH (c)-[:CITES]->(out:Case)
            OPTIONAL MATCH (inc:Case)-[:CITES]->(c)
            RETURN collect(DISTINCT j.name) AS judges,
                   collect(DISTINCT s.label) AS statutes,
                   collect(DISTINCT {id: out.id, title: out.title})[..25] AS cites,
                   collect(DISTINCT {id: inc.id, title: inc.title})[..25] AS cited_by
            """,
            id=case_id,
        )
        if not rows:
            return {}
        row = rows[0]
        row["cites"] = [c for c in row["cites"] if c.get("id")]
        row["cited_by"] = [c for c in row["cited_by"] if c.get("id")]
        return row

    async def counts(self) -> dict[str, int]:
        rows = await self._read(
            """
            CALL () { MATCH (c:Case {indexed: true}) RETURN count(c) AS cases }
            CALL () { MATCH (k:Chunk) RETURN count(k) AS chunks }
            CALL () { MATCH (s:Section) RETURN count(s) AS sections }
            CALL () { MATCH (j:Judge) RETURN count(j) AS judges }
            CALL () { MATCH ()-[r:CITES]->() RETURN count(r) AS citations }
            RETURN cases, chunks, sections, judges, citations
            """
        )
        return rows[0] if rows else {}
