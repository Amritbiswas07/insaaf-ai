"""Shared fakes so the suite runs without Neo4j, MongoDB or an LLM server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from insaaf.config import Settings
from insaaf.llm import LLMResponse, Message, ToolSpec

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings() -> Settings:
    return Settings(env="test", _env_file=None, api_keys=[], authority_weight=0.15)


@pytest.fixture
def judgment_html() -> str:
    return (FIXTURES / "judgment.html").read_text()


@pytest.fixture
def search_html() -> str:
    return (FIXTURES / "search.html").read_text()


class FakeEmbedder:
    dim = 4

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)), 0.0, 0.0, 1.0] for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0, 0.0]


CASES: dict[str, dict[str, Any]] = {
    "111": {"id": "111", "title": "Ramesh Kumar vs State", "court": "Bombay High Court", "date": "2023-03-12",
            "year": 2023, "url": "https://indiankanoon.org/doc/111/", "summary": "Bail granted after delay.",
            "holding": "Prolonged incarceration justifies bail.", "outcome": "bail_granted",
            "cited_by_count": 27, "statutes": ["Section 439 CrPC"]},
    "222": {"id": "222", "title": "Sanjay Chandra vs CBI", "court": "Supreme Court of India", "date": "2011-11-23",
            "year": 2011, "url": "https://indiankanoon.org/doc/222/", "summary": "Bail is the rule.",
            "holding": None, "outcome": "bail_granted", "cited_by_count": 4000, "statutes": []},
    "444": {"id": "444", "title": "Old Case vs State", "court": "Bombay High Court", "date": "1999-01-01",
            "year": 1999, "url": "https://indiankanoon.org/doc/444/", "summary": None, "holding": None,
            "outcome": None, "cited_by_count": 0, "statutes": []},
}


class FakeGraph:
    def __init__(self) -> None:
        self.dense = [
            {"chunk_id": "111:0", "case_id": "111", "text": "delay in trial bail", "roles": ["Issue"], "score": 0.9},
            {"chunk_id": "444:0", "case_id": "444", "text": "old matter", "roles": ["Other"], "score": 0.5},
            {"chunk_id": "222:1", "case_id": "222", "text": "bail is the rule", "roles": ["Conclusion"], "score": 0.4},
        ]
        self.sparse = [
            {"chunk_id": "222:1", "case_id": "222", "text": "bail is the rule", "roles": ["Conclusion"], "score": 7.0},
            {"chunk_id": "111:1", "case_id": "111", "text": "section 439 crpc", "roles": ["Section"], "score": 5.0},
        ]

    async def ping(self) -> bool:
        return True

    async def vector_search(self, embedding: list[float], k: int) -> list[dict[str, Any]]:
        return self.dense[:k]

    async def fulltext_search(self, query: str, k: int) -> list[dict[str, Any]]:
        return self.sparse[:k]

    async def cases_meta(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        return {i: CASES[i] for i in ids if i in CASES}

    async def co_cited_precedents(self, case_ids: list[str], **_: Any) -> list[dict[str, Any]]:
        return [{"id": "999", "title": "Leading Precedent vs State", "court": "Supreme Court of India",
                 "date": "1980-01-01", "url": "https://indiankanoon.org/doc/999/", "summary": None, "support": 2}]

    async def related_cases(self, case_id: str, relation: str, limit: int = 10) -> list[dict[str, Any]]:
        return [CASES["222"]] if relation == "cites" else []

    async def cases_for_section(self, act: str, section: str | None, limit: int = 15) -> list[dict[str, Any]]:
        return [{**CASES["111"], "section": f"Section {section} {act}", "mentions": 3}]

    async def case_graph(self, case_id: str) -> dict[str, Any]:
        return {"judges": ["A. B. Judge"], "statutes": ["Section 439 CrPC"], "cites": [{"id": "222", "title": "Sanjay Chandra vs CBI"}], "cited_by": []}

    async def counts(self) -> dict[str, int]:
        return {"cases": 3, "chunks": 5, "sections": 1, "judges": 1, "citations": 1}

    async def close(self) -> None:
        pass


class FakeRepo:
    async def ping(self) -> bool:
        return True

    async def get(self, doc_id: str, projection: Any = None) -> dict[str, Any] | None:
        if doc_id != "111":
            return None
        return {
            "_id": "111", "title": "Ramesh Kumar vs State", "url": "https://indiankanoon.org/doc/111/",
            "court": "Bombay High Court", "decision_date": "2023-03-12", "bench": ["A. B. Judge"],
            "parties": [{"name": "Ramesh Kumar", "role": "petitioner"}],
            "insights": {"summary": "Bail granted.", "case_type": "bail application", "legal_issues": ["delay"],
                         "holding": "Bail granted.", "outcome": "bail_granted", "key_principles": ["bail is the rule"]},
            "statutes": [{"act": "CrPC", "section": "439", "key": "CrPC::439", "label": "Section 439 CrPC", "mentions": 2}],
            "paragraphs": [{"idx": 0, "role": "Issue", "text": "Whether bail..."},
                           {"idx": 1, "role": "Conclusion", "text": "Application allowed."}],
            "status": "indexed",
        }

    async def status_counts(self) -> dict[str, int]:
        return {"indexed": 3}

    async def close(self) -> None:
        pass


class ScriptedLLM:
    """Returns pre-scripted responses in order; records the messages it saw."""

    model = "scripted"

    def __init__(self, responses: list[LLMResponse], stream_text: str = "") -> None:
        self.responses = list(responses)
        self.stream_text = stream_text
        self.calls: list[list[Message]] = []

    async def complete(self, messages: list[Message], *, tools: list[ToolSpec] | None = None, **_: Any) -> LLMResponse:
        self.calls.append(list(messages))
        return self.responses.pop(0)

    async def stream(self, messages: list[Message], **_: Any) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        for word in self.stream_text.split(" "):
            yield word + " "
