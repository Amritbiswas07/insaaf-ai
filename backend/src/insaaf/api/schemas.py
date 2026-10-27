from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    stream: bool = True
    mode: Literal["agent", "rag"] | None = None

    @field_validator("messages")
    @classmethod
    def _last_is_user(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if v[-1].role != "user" or not v[-1].content.strip():
            raise ValueError("the last message must be a non-empty user message")
        return v


class ChatResponse(BaseModel):
    answer: str
    citations: dict[str, Any]
    tool_calls: int
    latency_ms: int
    model: str


class PassageOut(BaseModel):
    text: str
    roles: list[str]


class CaseHitOut(BaseModel):
    id: str
    title: str
    court: str | None
    date: str | None
    url: str | None
    summary: str | None
    outcome: str | None
    statutes: list[str]
    cited_by_count: int
    score: float
    passages: list[PassageOut]


class SearchResponse(BaseModel):
    query: str
    results: list[CaseHitOut]
    precedents: list[dict[str, Any]]


class CaseDetail(BaseModel):
    id: str
    title: str
    url: str | None
    court: str | None
    decision_date: str | None
    bench: list[str]
    parties: list[dict[str, Any]]
    insights: dict[str, Any] | None
    statutes: list[dict[str, Any]]
    paragraphs: list[dict[str, Any]]
    graph: dict[str, Any]
    status: str | None
