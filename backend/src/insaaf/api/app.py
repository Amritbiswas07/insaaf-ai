"""HTTP API.

POST /api/chat          research agent (SSE stream or JSON)
GET  /api/search        hybrid case search
GET  /api/cases/{id}    full judgment + insights + graph neighbourhood
GET  /api/stats         corpus / pipeline statistics
GET  /api/health        liveness + dependency checks
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import APIKeyHeader

from insaaf import __version__
from insaaf.agent import AgentEvent, ChatTurn
from insaaf.api.schemas import (
    CaseDetail,
    CaseHitOut,
    ChatRequest,
    ChatResponse,
    PassageOut,
    SearchResponse,
)
from insaaf.config import Settings, get_settings
from insaaf.container import Container
from insaaf.logs import configure_logging, log
from insaaf.retrieval import SearchFilters

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


def require_key(request: Request, key: Annotated[str | None, Depends(_api_key_header)]) -> None:
    keys = request.app.state.settings.api_keys
    if keys and key not in keys:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


C = Annotated[Container, Depends(get_container)]


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or Container.build(settings)
        log.info("api.started", version=__version__, chat_model=settings.chat_model)
        yield
        await app.state.container.aclose()

    app = FastAPI(title="Insaaf AI", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Any:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        structlog.contextvars.bind_contextvars(request_id=rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        response.headers["x-request-id"] = rid
        if request.url.path != "/api/health":
            log.info(
                "http.request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=int((time.perf_counter() - start) * 1000),
                request_id=rid,
            )
        return response

    app.state.settings = settings
    auth = [Depends(require_key)]

    # ----------------------------------------------------------------- health

    @app.get("/api/health")
    async def health(c: C) -> JSONResponse:
        async def check(coro: Any) -> str:
            try:
                await asyncio.wait_for(coro, timeout=3)
                return "ok"
            except Exception as exc:  # noqa: BLE001
                return f"error: {exc.__class__.__name__}"

        mongo, neo = await asyncio.gather(check(c.repo.ping()), check(c.graph.ping()))
        ok = mongo == "ok" and neo == "ok"
        return JSONResponse(
            {"status": "ok" if ok else "degraded", "version": __version__, "mongo": mongo, "neo4j": neo},
            status_code=200 if ok else 503,
        )

    @app.get("/api/stats", dependencies=auth)
    async def stats(c: C) -> dict[str, Any]:
        pipeline, graph = await asyncio.gather(c.repo.status_counts(), c.graph.counts())
        return {
            "pipeline": pipeline,
            "graph": graph,
            "models": {"chat": settings.chat_model, "extract": settings.extract_model, "embed": settings.embed_model},
        }

    # ----------------------------------------------------------------- chat

    def sse(event: AgentEvent) -> str:
        return f"event: {event.type}\ndata: {json.dumps(event.data, default=str)}\n\n"

    @app.post("/api/chat", dependencies=auth, response_model=None)
    async def chat(body: ChatRequest, c: C) -> StreamingResponse | ChatResponse:
        *history, last = body.messages
        turns = [ChatTurn(m.role, m.content) for m in history]
        agent = c.agent(body.mode)
        events = agent.run(last.content.strip(), turns)

        if body.stream:
            async def gen() -> AsyncIterator[str]:
                async for ev in events:
                    yield sse(ev)

            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        citations: dict[str, Any] = {}
        async for ev in events:
            if ev.type == "citations":
                citations = ev.data
            elif ev.type == "error":
                raise HTTPException(status_code=502, detail=ev.data.get("message"))
            elif ev.type == "done":
                return ChatResponse(citations=citations, **ev.data)
        raise HTTPException(status_code=500, detail="agent produced no answer")

    # ----------------------------------------------------------------- search

    @app.get("/api/search", dependencies=auth)
    async def search(
        c: C,
        q: Annotated[str, Query(min_length=2, max_length=500)],
        court: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: Annotated[int, Query(ge=1, le=30)] = 10,
    ) -> SearchResponse:
        result = await c.retriever.search(q, SearchFilters(court, year_from, year_to), top_cases=limit)
        return SearchResponse(
            query=q,
            results=[
                CaseHitOut(
                    id=h.case_id,
                    title=h.title,
                    court=h.court,
                    date=h.date,
                    url=h.url,
                    summary=h.summary,
                    outcome=h.outcome,
                    statutes=h.statutes,
                    cited_by_count=h.cited_by_count,
                    score=round(h.score, 5),
                    passages=[PassageOut(text=p.text, roles=p.roles) for p in h.passages],
                )
                for h in result.cases
            ],
            precedents=result.precedents,
        )

    # ----------------------------------------------------------------- cases

    @app.get("/api/cases/{case_id}", dependencies=auth)
    async def case_detail(case_id: str, c: C) -> CaseDetail:
        if not case_id.isdigit():
            raise HTTPException(status_code=400, detail="case id must be numeric")
        doc, graph = await asyncio.gather(c.repo.get(case_id, {"links": 0}), c.graph.case_graph(case_id))
        if not doc or not doc.get("title"):
            raise HTTPException(status_code=404, detail="case not found")
        return CaseDetail(
            id=case_id,
            title=doc["title"],
            url=doc.get("url"),
            court=doc.get("court"),
            decision_date=doc.get("decision_date"),
            bench=doc.get("bench") or [],
            parties=doc.get("parties") or [],
            insights=doc.get("insights"),
            statutes=doc.get("statutes") or [],
            paragraphs=doc.get("paragraphs") or [],
            graph=graph,
            status=doc.get("status"),
        )

    return app


def app() -> FastAPI:  # uvicorn --factory insaaf.api.app:app
    return create_app()
