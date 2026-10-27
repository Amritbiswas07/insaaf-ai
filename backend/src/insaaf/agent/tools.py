"""Tools the research agent can call, plus the registry that tracks every
source the agent has actually seen (used to verify citations)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from insaaf.llm import ToolSpec
from insaaf.processing.statutes import canonical_act, canonical_section
from insaaf.retrieval import CaseHit, HybridRetriever, RetrievalResult, SearchFilters
from insaaf.storage import GraphStore, MongoRepo

PASSAGE_CHARS = 700


@dataclass(slots=True)
class Source:
    id: str
    title: str
    court: str | None = None
    date: str | None = None
    url: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def add(self, row: dict[str, Any] | CaseHit) -> None:
        if isinstance(row, CaseHit):
            row = {"id": row.case_id, "title": row.title, "court": row.court, "date": row.date, "url": row.url, "summary": row.summary}
        cid = str(row.get("id") or "")
        if not cid or cid in self._sources:
            return
        self._sources[cid] = Source(
            id=cid,
            title=row.get("title") or f"Document {cid}",
            court=row.get("court"),
            date=row.get("date"),
            url=row.get("url") or f"https://indiankanoon.org/doc/{cid}/",
            summary=row.get("summary"),
        )

    def __contains__(self, cid: str) -> bool:
        return cid in self._sources

    def get(self, cid: str) -> Source | None:
        return self._sources.get(cid)

    def all(self) -> list[Source]:
        return list(self._sources.values())


def _clip(text: str | None, n: int) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def format_case_hit(h: CaseHit) -> str:
    lines = [f"[doc:{h.case_id}] {h.title} ({h.court or 'court n/a'}, {h.date or 'date n/a'}) — cited by {h.cited_by_count}"]
    if h.outcome or h.statutes:
        lines.append(f"  Outcome: {h.outcome or 'n/a'} | Provisions: {', '.join(h.statutes[:8]) or 'n/a'}")
    if h.summary:
        lines.append(f"  Summary: {_clip(h.summary, 600)}")
    for p in h.passages:
        role = f"({', '.join(p.roles)}) " if p.roles and p.roles != ["Other"] else ""
        lines.append(f"  • {role}\"{_clip(p.text, PASSAGE_CHARS)}\"")
    return "\n".join(lines)


def format_retrieval(result: RetrievalResult) -> str:
    if not result.cases:
        return "No matching judgments found in the indexed corpus."
    parts = [format_case_hit(h) for h in result.cases]
    if result.precedents:
        parts.append("Leading precedents cited by several of the above judgments:")
        parts.extend(
            f"[doc:{p['id']}] {p.get('title') or 'untitled'} — cited by {p['support']} of the retrieved cases"
            for p in result.precedents
        )
    return "\n\n".join(parts)


def _format_rows(rows: list[dict[str, Any]], extra: str | None = None) -> str:
    if not rows:
        return "No results."
    out = []
    for r in rows:
        line = f"[doc:{r['id']}] {r.get('title') or 'untitled (not yet ingested)'} ({r.get('court') or 'n/a'}, {r.get('date') or 'n/a'})"
        if extra and r.get(extra):
            val = r[extra]
            line += f" — {extra}: {', '.join(val) if isinstance(val, list) else val}"
        if r.get("summary"):
            line += f"\n  Summary: {_clip(r['summary'], 400)}"
        out.append(line)
    return "\n".join(out)


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="search_case_law",
        description=(
            "Hybrid semantic + keyword search over indexed Indian judgments. Use for any "
            "new legal question or angle. Returns the most relevant cases with passages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Focused legal search query."},
                "court": {"type": "string", "description": "Optional court filter, e.g. 'Bombay High Court'."},
                "year_from": {"type": "integer"},
                "year_to": {"type": "integer"},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="get_case_details",
        description="Read a judgment in depth: summary, issues, holding, principles and key paragraphs.",
        parameters={
            "type": "object",
            "properties": {"case_id": {"type": "string", "description": "The numeric id from [doc:ID]."}},
            "required": ["case_id"],
        },
    ),
    ToolSpec(
        name="find_related_cases",
        description=(
            "Traverse the citation/knowledge graph from a case. relation = 'cites' (precedents it relies on), "
            "'cited_by' (later cases relying on it), 'shares_statutes' (cases applying the same provisions), "
            "'same_bench' (other decisions of the same judges)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "case_id": {"type": "string"},
                "relation": {"type": "string", "enum": ["cites", "cited_by", "shares_statutes", "same_bench"]},
            },
            "required": ["case_id", "relation"],
        },
    ),
    ToolSpec(
        name="cases_applying_statute",
        description="List judgments that apply a specific statutory provision, e.g. act='IPC', section='302'.",
        parameters={
            "type": "object",
            "properties": {
                "act": {"type": "string", "description": "Act name or abbreviation (IPC, CrPC, BNS, NDPS Act, Constitution…)."},
                "section": {"type": "string", "description": "Section/article number, e.g. '438' or '21'."},
            },
            "required": ["act"],
        },
    ),
]


class LegalTools:
    def __init__(self, retriever: HybridRetriever, graph: GraphStore, repo: MongoRepo) -> None:
        self.retriever = retriever
        self.graph = graph
        self.repo = repo
        self.specs = TOOL_SPECS

    async def search(self, registry: SourceRegistry, query: str, filters: SearchFilters | None = None) -> str:
        result = await self.retriever.search(query, filters)
        for h in result.cases:
            registry.add(h)
        for p in result.precedents:
            registry.add(p)
        return format_retrieval(result)

    async def run(self, name: str, args: dict[str, Any], registry: SourceRegistry) -> str:
        try:
            if name == "search_case_law":
                filters = SearchFilters(
                    court=args.get("court") or None,
                    year_from=_as_int(args.get("year_from")),
                    year_to=_as_int(args.get("year_to")),
                )
                return await self.search(registry, str(args.get("query", "")), filters)
            if name == "get_case_details":
                return await self._case_details(str(args.get("case_id", "")).strip(), registry)
            if name == "find_related_cases":
                rows = await self.graph.related_cases(str(args["case_id"]), str(args["relation"]))
                for r in rows:
                    registry.add(r)
                return _format_rows(rows, extra="shared" if args["relation"] == "shares_statutes" else None)
            if name == "cases_applying_statute":
                act, _ = canonical_act(str(args.get("act", "")))
                section = canonical_section(str(args["section"])) if args.get("section") else None
                rows = await self.graph.cases_for_section(act, section)
                for r in rows:
                    registry.add(r)
                return _format_rows(rows, extra="section")
            return f"Unknown tool {name!r}."
        except Exception as exc:  # noqa: BLE001 — tool errors go back to the model
            return f"Tool error: {exc}"

    async def _case_details(self, case_id: str, registry: SourceRegistry) -> str:
        doc = await self.repo.get(case_id)
        if not doc:
            return f"Case {case_id} is not in the corpus."
        registry.add({"id": case_id, **doc, "date": doc.get("decision_date")})
        ins = doc.get("insights") or {}
        paras = doc.get("paragraphs") or []
        key_paras = [p for p in paras if p.get("role") in ("Issue", "Conclusion")][:6] or paras[-4:]
        lines = [
            f"[doc:{case_id}] {doc.get('title')}",
            f"Court: {doc.get('court')} | Date: {doc.get('decision_date')} | Bench: {', '.join(doc.get('bench') or [])}",
            f"Provisions: {', '.join(s['label'] for s in (doc.get('statutes') or [])[:15]) or 'n/a'}",
        ]
        if ins:
            lines += [
                f"Case type: {ins.get('case_type')} | Outcome: {ins.get('outcome')}",
                f"Summary: {ins.get('summary')}",
                f"Issues: {'; '.join(ins.get('legal_issues') or [])}",
                f"Holding: {ins.get('holding')}",
                f"Principles: {'; '.join(ins.get('key_principles') or [])}",
            ]
        lines.append("Key paragraphs:")
        lines += [f"  ¶{p['idx']} ({p.get('role')}): {_clip(p['text'], 900)}" for p in key_paras]
        return "\n".join(lines)


def _as_int(v: Any) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None
