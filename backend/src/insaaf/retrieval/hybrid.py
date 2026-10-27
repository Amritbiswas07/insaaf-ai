"""Hybrid GraphRAG retrieval.

1. Dense (vector) and sparse (Lucene full-text) search over chunks, in parallel.
2. Reciprocal Rank Fusion at chunk level.
3. Aggregate to case level (best two chunks per case) and apply an
   "authority" prior from how often the judgment is cited.
4. Optional metadata filters (court, year range).
5. Graph expansion: precedents co-cited by several retrieved cases.
"""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from insaaf.config import Settings
from insaaf.llm import Embedder
from insaaf.storage import GraphStore


@dataclass(slots=True)
class SearchFilters:
    court: str | None = None
    year_from: int | None = None
    year_to: int | None = None

    @property
    def active(self) -> bool:
        return any(v is not None for v in (self.court, self.year_from, self.year_to))

    def accepts(self, meta: dict[str, Any]) -> bool:
        if self.court and self.court.lower() not in (meta.get("court") or "").lower():
            return False
        year = meta.get("year")
        if self.year_from and (year is None or year < self.year_from):
            return False
        return not (self.year_to and (year is None or year > self.year_to))


@dataclass(slots=True)
class Passage:
    chunk_id: str
    text: str
    roles: list[str]
    score: float


@dataclass(slots=True)
class CaseHit:
    case_id: str
    score: float
    title: str
    court: str | None
    date: str | None
    url: str | None
    summary: str | None
    holding: str | None
    outcome: str | None
    statutes: list[str]
    cited_by_count: int
    passages: list[Passage] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalResult:
    cases: list[CaseHit]
    precedents: list[dict[str, Any]]


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]], k: int = 60, weights: Sequence[float] | None = None
) -> dict[str, float]:
    """Standard RRF: score(d) = Σ w_i / (k + rank_i(d)), ranks starting at 1."""
    weights = weights or [1.0] * len(ranked_lists)
    scores: dict[str, float] = defaultdict(float)
    for w, ranked in zip(weights, ranked_lists, strict=True):
        for rank, item in enumerate(ranked, start=1):
            scores[item] += w / (k + rank)
    return dict(scores)


def authority_multiplier(cited_by: int, weight: float, saturation: int = 500) -> float:
    if weight <= 0 or cited_by <= 0:
        return 1.0
    return 1.0 + weight * min(1.0, math.log1p(cited_by) / math.log1p(saturation))


class HybridRetriever:
    def __init__(self, graph: GraphStore, embedder: Embedder, settings: Settings) -> None:
        self.graph = graph
        self.embedder = embedder
        self.s = settings

    async def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        top_cases: int | None = None,
        expand_graph: bool = True,
    ) -> RetrievalResult:
        filters = filters or SearchFilters()
        top_cases = top_cases or self.s.retrieval_top_cases
        k = self.s.retrieval_k * (3 if filters.active else 1)

        qvec = await self.embedder.embed_query(query)
        dense, sparse = await asyncio.gather(
            self.graph.vector_search(qvec, k), self.graph.fulltext_search(query, k)
        )

        chunks: dict[str, dict[str, Any]] = {}
        for row in [*dense, *sparse]:
            chunks.setdefault(row["chunk_id"], row)
        fused = reciprocal_rank_fusion(
            [[r["chunk_id"] for r in dense], [r["chunk_id"] for r in sparse]], k=self.s.rrf_k
        )

        by_case: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for chunk_id, score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True):
            by_case[chunks[chunk_id]["case_id"]].append((chunk_id, score))

        meta = await self.graph.cases_meta(list(by_case))
        hits: list[CaseHit] = []
        for case_id, scored in by_case.items():
            m = meta.get(case_id)
            if not m or not filters.accepts(m):
                continue
            top2 = scored[:2]
            base = top2[0][1] + 0.5 * (top2[1][1] if len(top2) > 1 else 0.0)
            score = base * authority_multiplier(m.get("cited_by_count") or 0, self.s.authority_weight)
            hits.append(
                CaseHit(
                    case_id=case_id,
                    score=score,
                    title=m.get("title") or case_id,
                    court=m.get("court"),
                    date=m.get("date"),
                    url=m.get("url"),
                    summary=m.get("summary"),
                    holding=m.get("holding"),
                    outcome=m.get("outcome"),
                    statutes=m.get("statutes") or [],
                    cited_by_count=m.get("cited_by_count") or 0,
                    passages=[
                        Passage(cid, chunks[cid]["text"], chunks[cid].get("roles") or [], s)
                        for cid, s in top2
                    ],
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        hits = hits[:top_cases]

        precedents: list[dict[str, Any]] = []
        if expand_graph and len(hits) >= 2:
            precedents = await self.graph.co_cited_precedents([h.case_id for h in hits])
        return RetrievalResult(cases=hits, precedents=precedents)
