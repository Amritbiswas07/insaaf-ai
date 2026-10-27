"""Resumable ingestion pipeline.

    discover ─▶ fetch+parse ─▶ enrich (LLM) ─▶ index (embeddings + graph)

Every stage reads its input set from MongoDB by `status`, so any stage can be
stopped and restarted, run on a schedule, or scaled out independently.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from insaaf.config import Settings
from insaaf.domain import CaseInsights, Judgment, ProcessingStatus, StatuteRef
from insaaf.llm import ChatLLM, Embedder
from insaaf.logs import log
from insaaf.processing import statutes as st
from insaaf.processing.chunker import chunk_judgment, embedding_text
from insaaf.processing.enrich import enrich_judgment
from insaaf.scraper.http import RobotsDisallowed
from insaaf.scraper.kanoon import KanoonSource, month_windows
from insaaf.scraper.parser import parse_doc_header, parse_judgment
from insaaf.storage import GraphStore, MongoRepo

S = ProcessingStatus


@dataclass
class StageReport:
    stage: str
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.stage}: ok={self.ok} failed={self.failed} skipped={self.skipped}"


async def _run_bounded(
    ids: list[str], concurrency: int, fn: Callable[[str], Awaitable[None]]
) -> None:
    sem = asyncio.Semaphore(concurrency)

    async def one(i: str) -> None:
        async with sem:
            await fn(i)

    await asyncio.gather(*(one(i) for i in ids))


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        repo: MongoRepo,
        graph: GraphStore | None = None,
        source: KanoonSource | None = None,
        extract_llm: ChatLLM | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.s = settings
        self.repo = repo
        self.graph = graph
        self.source = source
        self.extract_llm = extract_llm
        self.embedder = embedder

    # ----------------------------------------------------------------- discover

    async def discover(self, court: str, year_from: int, year_to: int, query: str = "", limit: int | None = None) -> StageReport:
        assert self.source, "discover requires a KanoonSource"
        report = StageReport("discover")
        base = f"{query} doctypes:{court}".strip()
        buffer = []
        async for _, hit in self.source.discover(base, month_windows(year_from, year_to)):
            buffer.append(hit)
            if len(buffer) >= 100:
                report.ok += await self.repo.upsert_discovered(buffer, base)
                buffer.clear()
            if limit and report.ok + len(buffer) >= limit:
                break
        report.ok += await self.repo.upsert_discovered(buffer, base)
        return report

    # ----------------------------------------------------------------- fetch + parse

    async def fetch(self, limit: int, resolve_statutes: bool = True) -> StageReport:
        assert self.source, "fetch requires a KanoonSource"
        report = StageReport("fetch")
        ids = await self.repo.ids_with_status(S.DISCOVERED, limit)

        async def one(doc_id: str) -> None:
            try:
                html = await self.source.fetch_doc_html(doc_id)  # type: ignore[union-attr]
                await self.repo.save_raw_html(doc_id, html)
                await self._parse_and_store(doc_id, html, resolve_statutes)
                report.ok += 1
            except RobotsDisallowed:
                await self.repo.mark(doc_id, S.SKIPPED, error={"stage": "fetch", "message": "robots.txt"})
                report.skipped += 1
            except Exception as exc:  # noqa: BLE001 — record and continue
                log.exception("fetch.failed", doc_id=doc_id)
                await self.repo.mark_failed(doc_id, "fetch", repr(exc))
                report.failed += 1

        await _run_bounded(ids, self.s.scraper_concurrency, one)
        return report

    async def reparse(self, limit: int, resolve_statutes: bool = False) -> StageReport:
        """Re-run the parser over stored HTML (after parser improvements)."""
        report = StageReport("reparse")
        ids = await self.repo.ids_with_status([S.FETCHED, S.PARSED, S.ENRICHED, S.INDEXED], limit, max_attempts=99)
        for doc_id in ids:
            html = await self.repo.get_raw_html(doc_id)
            if not html:
                report.skipped += 1
                continue
            prior = await self.repo.get(doc_id, {"status": 1, "insights": 1})
            await self._parse_and_store(doc_id, html, resolve_statutes)
            if prior and prior.get("insights"):
                # Keep LLM output; re-index with the new parse.
                await self.repo.mark(doc_id, S.ENRICHED)
            report.ok += 1
        return report

    async def _parse_and_store(self, doc_id: str, html: str, resolve_statutes: bool) -> None:
        j = parse_judgment(doc_id, html, self.s.kanoon_base_url)
        if not j.paragraphs:
            await self.repo.mark(doc_id, S.SKIPPED, error={"stage": "parse", "message": "no text"})
            return
        statutes, citations = await self._extract_refs(j, resolve_statutes)
        await self.repo.save_parsed(j, statutes, citations)

    async def _extract_refs(
        self, j: Judgment, resolve: bool
    ) -> tuple[list[tuple[StatuteRef, int]], list[dict[str, Any]]]:
        refs: list[StatuteRef] = []
        for p in j.paragraphs:
            refs.extend(st.extract_from_text(p.text))

        statute_links, case_links = st.split_links(j.links)
        cache = await self.repo.cached_links([link.doc_id for link in j.links])

        for link in list(statute_links):
            hit = cache.get(link.doc_id)
            if hit is None and resolve and self.source:
                hit = await self._resolve_link(link.doc_id)
            if not hit:
                continue
            if hit["kind"] == "statute" and hit.get("statute"):
                ref = StatuteRef.model_validate(hit["statute"])
                refs.extend([ref] * link.count)
            elif hit["kind"] == "case":
                statute_links.remove(link)
                case_links.append(link)

        for link in list(case_links):
            hit = cache.get(link.doc_id)
            if hit and hit["kind"] == "statute" and hit.get("statute"):
                case_links.remove(link)
                refs.extend([StatuteRef.model_validate(hit["statute"])] * link.count)

        citations = [{"doc_id": link.doc_id, "anchor": link.anchor_text, "mentions": link.count} for link in case_links]
        return st.dedupe(refs), citations

    async def _resolve_link(self, doc_id: str) -> dict[str, Any] | None:
        try:
            html = await self.source.fetch_doc_html(doc_id)  # type: ignore[union-attr]
        except RobotsDisallowed:
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("resolve.failed", doc_id=doc_id, error=repr(exc))
            return None
        title, source = parse_doc_header(html)
        ref = st.ref_from_ik_title(title or "", doc_id)
        if ref:
            kind = "statute"
        elif title and (" vs " in title.lower() or " v. " in title.lower()):
            kind = "case"
        elif source and ("Act" in source or "Constitution" in source):
            kind = "act"
        else:
            kind = "other"
        await self.repo.cache_link(doc_id, title, source, kind, ref)
        return {"kind": kind, "statute": ref.model_dump() if ref else None, "title": title}

    # ----------------------------------------------------------------- enrich

    async def enrich(self, limit: int, concurrency: int = 2) -> StageReport:
        assert self.extract_llm, "enrich requires an extraction LLM"
        report = StageReport("enrich")
        ids = await self.repo.ids_with_status(S.PARSED, limit)

        async def one(doc_id: str) -> None:
            doc = await self.repo.get(doc_id)
            if not doc:
                return
            try:
                j = Judgment.model_validate({**doc, "doc_id": doc_id})
                insights = await enrich_judgment(self.extract_llm, j, self.s.enrich_max_context_chars)  # type: ignore[arg-type]
                await self.repo.save_insights(doc_id, insights)
                report.ok += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("enrich.failed", doc_id=doc_id)
                await self.repo.mark_failed(doc_id, "enrich", repr(exc))
                report.failed += 1

        await _run_bounded(ids, concurrency, one)
        return report

    # ----------------------------------------------------------------- index

    async def index(self, limit: int, include_unenriched: bool = False, concurrency: int = 2) -> StageReport:
        assert self.graph and self.embedder, "index requires graph + embedder"
        report = StageReport("index")
        await self.graph.ensure_schema(self.s.embed_dim)
        statuses = [S.ENRICHED, S.PARSED] if include_unenriched else [S.ENRICHED]
        ids = await self.repo.ids_with_status(statuses, limit)

        async def one(doc_id: str) -> None:
            doc = await self.repo.get(doc_id)
            if not doc:
                return
            try:
                j = Judgment.model_validate({**doc, "doc_id": doc_id})
                insights = CaseInsights.model_validate(doc["insights"]) if doc.get("insights") else None
                statutes = [(StatuteRef.model_validate(s), s.get("mentions", 1)) for s in doc.get("statutes", [])]
                cited = [(c["doc_id"], c.get("mentions", 1)) for c in doc.get("citations", [])]
                chunks = chunk_judgment(j, self.s.chunk_target_chars, self.s.chunk_overlap_paras)
                vectors = await self.embedder.embed_documents([embedding_text(j, c) for c in chunks])  # type: ignore[union-attr]
                await self.graph.upsert_case(j, insights, statutes, cited, chunks, vectors)  # type: ignore[union-attr]
                await self.repo.mark(doc_id, S.INDEXED, chunks=len(chunks), error=None)
                report.ok += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("index.failed", doc_id=doc_id)
                await self.repo.mark_failed(doc_id, "index", repr(exc))
                report.failed += 1

        await _run_bounded(ids, concurrency, one)
        return report


def summarize_statuses(counts: dict[str, int]) -> str:
    c = Counter(counts)
    order = [s.value for s in S]
    return "  ".join(f"{k}={c.get(k, 0)}" for k in order)
