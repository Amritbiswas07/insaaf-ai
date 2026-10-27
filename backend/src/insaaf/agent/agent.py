"""Retrieval-first research agent.

Every question starts grounded: hybrid GraphRAG retrieval runs *before* the
model's first turn and its results are placed in the prompt. Small local
models (Llama 3.1 8B) that are unreliable at deciding to call tools still
answer from real sources; stronger models (GPT-OSS, Claude) then use tools to
dig deeper — following citations, reading full judgments, pivoting on statutes.

The agent yields typed events so the API can stream progress to the UI.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

from insaaf.agent.prompts import FINALIZE, SOURCES_PREAMBLE, SYSTEM_PROMPT
from insaaf.agent.tools import LegalTools, SourceRegistry
from insaaf.llm import ChatLLM, Message
from insaaf.logs import log

EventType = Literal["status", "tool_call", "tool_result", "token", "citations", "done", "error"]
CITATION_RE = re.compile(r"\[doc:(\d+)\]")
HISTORY_TURNS = 8


@dataclass(slots=True)
class AgentEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


def _chunks(text: str, size: int = 48) -> list[str]:
    """Split a finished answer into word-aligned pieces for streaming."""
    out, buf = [], ""
    for word in re.split(r"(\s+)", text):
        buf += word
        if len(buf) >= size:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def citation_report(answer: str, registry: SourceRegistry) -> dict[str, Any]:
    cited_ids = list(dict.fromkeys(CITATION_RE.findall(answer)))
    verified = [registry.get(c).to_dict() for c in cited_ids if c in registry]  # type: ignore[union-attr]
    unverified = [c for c in cited_ids if c not in registry]
    consulted = [s.to_dict() for s in registry.all() if s.id not in cited_ids]
    return {"cited": verified, "unverified": unverified, "consulted": consulted}


class LegalAgent:
    def __init__(self, llm: ChatLLM, tools: LegalTools, max_steps: int = 6, mode: str = "agent") -> None:
        self.llm = llm
        self.tools = tools
        self.max_steps = max_steps
        self.mode = mode

    async def run(self, question: str, history: list[ChatTurn] | None = None) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        registry = SourceRegistry()
        tool_calls = 0
        try:
            yield AgentEvent("status", {"message": "Searching the case-law graph"})
            sources = await self.tools.search(registry, question)
            yield AgentEvent(
                "tool_result",
                {"name": "search_case_law", "args": {"query": question}, "sources": len(registry.all())},
            )

            messages = [Message("system", SYSTEM_PROMPT)]
            for turn in (history or [])[-HISTORY_TURNS:]:
                messages.append(Message(turn.role, turn.content))
            messages.append(
                Message("user", f"{SOURCES_PREAMBLE.format(sources=sources)}\n\nQuestion: {question}")
            )

            if self.mode == "rag":
                yield AgentEvent("status", {"message": "Writing answer"})
                answer = ""
                async for piece in self.llm.stream(messages, max_tokens=2500):
                    answer += piece
                    yield AgentEvent("token", {"text": piece})
            else:
                answer = ""
                for step in range(self.max_steps + 1):
                    final_step = step == self.max_steps
                    if final_step:
                        messages.append(Message("user", FINALIZE))
                    resp = await self.llm.complete(messages, tools=self.tools.specs, max_tokens=2500)
                    if not resp.tool_calls or final_step:
                        answer = resp.content
                        break
                    messages.append(
                        Message("assistant", resp.content, tool_calls=resp.tool_calls, raw=resp.raw)
                    )
                    for call in resp.tool_calls:
                        tool_calls += 1
                        yield AgentEvent("tool_call", {"name": call.name, "args": call.arguments})
                        result = await self.tools.run(call.name, call.arguments, registry)
                        messages.append(Message("tool", result, tool_call_id=call.id, name=call.name))
                        yield AgentEvent(
                            "tool_result",
                            {"name": call.name, "args": call.arguments, "sources": len(registry.all())},
                        )
                if not answer.strip():
                    answer = "I could not produce an answer from the available sources. Please rephrase or narrow the question."
                yield AgentEvent("status", {"message": "Writing answer"})
                for piece in _chunks(answer):
                    yield AgentEvent("token", {"text": piece})

            yield AgentEvent("citations", citation_report(answer, registry))
            yield AgentEvent(
                "done",
                {
                    "answer": answer,
                    "tool_calls": tool_calls,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "model": self.llm.model,
                },
            )
        except Exception as exc:  # noqa: BLE001 — surface as an event, keep the stream well-formed
            log.exception("agent.failed")
            yield AgentEvent("error", {"message": str(exc) or exc.__class__.__name__})
