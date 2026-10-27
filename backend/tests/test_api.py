import json

from fastapi.testclient import TestClient

from insaaf.agent import LegalTools
from insaaf.api.app import create_app
from insaaf.config import Settings
from insaaf.container import Container
from insaaf.llm import LLMResponse
from insaaf.retrieval import HybridRetriever

from .conftest import FakeEmbedder, FakeGraph, FakeRepo, ScriptedLLM


def client(settings: Settings, answers: int = 2) -> TestClient:
    graph, repo, emb = FakeGraph(), FakeRepo(), FakeEmbedder()
    retriever = HybridRetriever(graph, emb, settings)  # type: ignore[arg-type]
    container = Container(
        settings=settings,
        repo=repo,  # type: ignore[arg-type]
        graph=graph,  # type: ignore[arg-type]
        embedder=emb,
        chat_llm=ScriptedLLM([LLMResponse("Answer [doc:111].") for _ in range(answers)]),
        retriever=retriever,
        tools=LegalTools(retriever, graph, repo),  # type: ignore[arg-type]
    )
    return TestClient(create_app(settings, container))


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_health(settings: Settings) -> None:
    with client(settings) as c:
        r = c.get("/api/health")
    assert r.status_code == 200 and r.json()["neo4j"] == "ok"
    assert "x-request-id" in r.headers


def test_chat_json(settings: Settings) -> None:
    with client(settings) as c:
        r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "bail?"}], "stream": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "Answer [doc:111]."
    assert body["citations"]["cited"][0]["id"] == "111"


def test_chat_sse_stream(settings: Settings) -> None:
    with client(settings) as c:
        r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "bail?"}]})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert events[-1][0] == "done"
    assert any(name == "citations" for name, _ in events)


def test_chat_validation(settings: Settings) -> None:
    with client(settings) as c:
        r = c.post("/api/chat", json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert r.status_code == 422


def test_search_and_case(settings: Settings) -> None:
    with client(settings) as c:
        s = c.get("/api/search", params={"q": "bail delay", "limit": 2})
        d = c.get("/api/cases/111")
        missing = c.get("/api/cases/999")
        bad = c.get("/api/cases/abc")
    assert s.status_code == 200 and len(s.json()["results"]) == 2
    assert d.status_code == 200 and d.json()["graph"]["cites"][0]["id"] == "222"
    assert missing.status_code == 404 and bad.status_code == 400


def test_api_key_enforced(settings: Settings) -> None:
    secured = settings.model_copy(update={"api_keys": ["secret"]})
    with client(secured) as c:
        assert c.get("/api/stats").status_code == 401
        assert c.get("/api/stats", headers={"X-API-Key": "secret"}).status_code == 200
        assert c.get("/api/health").status_code == 200  # health stays public
