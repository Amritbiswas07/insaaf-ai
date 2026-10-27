"""`insaaf` command-line interface.

    insaaf init-db
    insaaf discover --court bombay --from 2020 --to 2024
    insaaf fetch --limit 500
    insaaf enrich --limit 500
    insaaf index --limit 500
    insaaf run --court bombay --from 2023 --to 2023 --limit 200   # all stages
    insaaf ask "When can anticipatory bail be refused under Section 438 CrPC?"
    insaaf serve
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from insaaf.config import get_settings
from insaaf.container import Container
from insaaf.logs import configure_logging
from insaaf.pipeline import Pipeline, StageReport, summarize_statuses
from insaaf.scraper import KanoonSource
from insaaf.storage import MongoRepo

app = typer.Typer(help="Insaaf AI — legal GraphRAG pipeline and agent.", no_args_is_help=True)
console = Console()
T = TypeVar("T")


def _run(fn: Callable[[], Awaitable[T]]) -> T:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    return asyncio.run(fn())


def _print(report: StageReport) -> None:
    style = "green" if report.failed == 0 else "yellow"
    console.print(f"[{style}]✔ {report}[/]")


@app.command("init-db")
def init_db() -> None:
    """Create MongoDB indexes and the Neo4j schema (constraints, vector + full-text indexes)."""

    async def go() -> None:
        c = Container.build(get_settings())
        try:
            await c.repo.ensure_indexes()
            await c.graph.ensure_schema(c.settings.embed_dim)
            console.print("[green]✔ MongoDB indexes and Neo4j schema ready[/]")
        finally:
            await c.aclose()

    _run(go)


@app.command()
def discover(
    court: Annotated[str, typer.Option(help="Indian Kanoon doctype, e.g. bombay, supremecourt, delhi")] = "bombay",
    year_from: Annotated[int, typer.Option("--from")] = 2023,
    year_to: Annotated[int, typer.Option("--to")] = 2023,
    query: Annotated[str, typer.Option(help="Optional topic filter, e.g. 'bail' or 'section 302'")] = "",
    limit: Annotated[int | None, typer.Option(help="Stop after this many documents")] = None,
) -> None:
    """Find judgment ids on Indian Kanoon and queue them."""

    async def go() -> None:
        s = get_settings()
        repo, source = MongoRepo(s.mongo_uri, s.mongo_db), KanoonSource(s)
        try:
            await repo.ensure_indexes()
            _print(await Pipeline(s, repo, source=source).discover(court, year_from, year_to, query, limit))
        finally:
            await source.aclose()
            await repo.close()

    _run(go)


@app.command()
def fetch(
    limit: int = 200,
    resolve_statutes: Annotated[bool, typer.Option(help="Look up linked statute pages to identify the Act")] = True,
) -> None:
    """Download and parse queued judgments."""

    async def go() -> None:
        s = get_settings()
        repo, source = MongoRepo(s.mongo_uri, s.mongo_db), KanoonSource(s)
        try:
            _print(await Pipeline(s, repo, source=source).fetch(limit, resolve_statutes))
        finally:
            await source.aclose()
            await repo.close()

    _run(go)


@app.command()
def reparse(limit: int = 100_000) -> None:
    """Re-run the parser on stored HTML (no network)."""

    async def go() -> None:
        s = get_settings()
        repo = MongoRepo(s.mongo_uri, s.mongo_db)
        try:
            _print(await Pipeline(s, repo).reparse(limit))
        finally:
            await repo.close()

    _run(go)


@app.command()
def enrich(limit: int = 200, concurrency: int = 2) -> None:
    """Generate structured case notes (summary, issues, holding, outcome) with the extraction LLM."""

    async def go() -> None:
        c = Container.build(get_settings())
        try:
            _print(await Pipeline(c.settings, c.repo, extract_llm=c.extract_llm()).enrich(limit, concurrency))
        finally:
            await c.aclose()

    _run(go)


@app.command()
def index(
    limit: int = 200,
    include_unenriched: Annotated[bool, typer.Option(help="Also index parsed docs without LLM notes")] = False,
    concurrency: int = 2,
) -> None:
    """Chunk, embed and write judgments into the Neo4j knowledge graph."""

    async def go() -> None:
        c = Container.build(get_settings())
        try:
            p = Pipeline(c.settings, c.repo, graph=c.graph, embedder=c.embedder)
            _print(await p.index(limit, include_unenriched, concurrency))
        finally:
            await c.aclose()

    _run(go)


@app.command()
def run(
    court: str = "bombay",
    year_from: Annotated[int, typer.Option("--from")] = 2023,
    year_to: Annotated[int, typer.Option("--to")] = 2023,
    query: str = "",
    limit: int = 100,
    skip_enrich: bool = False,
) -> None:
    """Run every stage end-to-end for a small batch."""

    async def go() -> None:
        c = Container.build(get_settings())
        source = KanoonSource(c.settings)
        try:
            await c.repo.ensure_indexes()
            p = Pipeline(c.settings, c.repo, c.graph, source, None if skip_enrich else c.extract_llm(), c.embedder)
            _print(await p.discover(court, year_from, year_to, query, limit))
            _print(await p.fetch(limit))
            if not skip_enrich:
                _print(await p.enrich(limit))
            _print(await p.index(limit, include_unenriched=skip_enrich))
            console.print(summarize_statuses(await c.repo.status_counts()))
        finally:
            await source.aclose()
            await c.aclose()

    _run(go)


@app.command()
def stats() -> None:
    """Show pipeline and graph statistics."""

    async def go() -> None:
        c = Container.build(get_settings())
        try:
            counts = await c.repo.status_counts()
            graph = await c.graph.counts()
        finally:
            await c.aclose()
        t = Table(title="Insaaf corpus")
        t.add_column("metric")
        t.add_column("value", justify="right")
        for k, v in sorted(counts.items()):
            t.add_row(f"pipeline.{k}", str(v))
        for k, v in graph.items():
            t.add_row(f"graph.{k}", str(v))
        console.print(t)

    _run(go)


@app.command()
def ask(
    question: str,
    mode: Annotated[str, typer.Option(help="agent | rag")] = "agent",
) -> None:
    """Ask the research agent a question from the terminal."""

    async def go() -> None:
        c = Container.build(get_settings())
        answer, citations = "", {}
        try:
            async for ev in c.agent(mode).run(question):
                if ev.type in ("status", "tool_call"):
                    label = ev.data.get("message") or f"{ev.data['name']}({ev.data.get('args')})"
                    console.print(f"[dim]› {label}[/]")
                elif ev.type == "citations":
                    citations = ev.data
                elif ev.type == "done":
                    answer = ev.data["answer"]
                elif ev.type == "error":
                    console.print(f"[red]error: {ev.data['message']}[/]")
        finally:
            await c.aclose()
        console.print(Markdown(answer))
        for src in citations.get("cited", []):
            console.print(f"[cyan][doc:{src['id']}][/] {src['title']} — {src['url']}")
        if citations.get("unverified"):
            console.print(f"[red]⚠ unverified citations: {citations['unverified']}[/]")

    _run(go)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    """Start the HTTP API."""
    import uvicorn

    uvicorn.run("insaaf.api.app:app", factory=True, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
