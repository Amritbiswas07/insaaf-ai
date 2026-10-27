"""OpenAI-compatible chat + embeddings (Ollama, vLLM, Groq, Together, OpenAI)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from insaaf.llm.base import LLMError, LLMResponse, Message, ToolCall, ToolSpec

_RETRYABLE = (APIConnectionError, APITimeoutError, RateLimitError)


def _to_openai(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content})
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _parse_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class OpenAICompatChat:
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        timeout_s: float = 180.0,
        temperature: float = 0.1,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai(messages),
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        if json_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": json_schema, "strict": True},
            }
        elif json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        resp = await self._client.chat.completions.create(**kwargs)
        if not resp.choices:
            raise LLMError("Empty completion")
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=_parse_args(tc.function.arguments))
            for tc in (msg.tool_calls or [])
            if tc.type == "function"
        ]
        return LLMResponse(content=msg.content or "", tool_calls=calls)

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        resp = await self._client.chat.completions.create(
            model=self.model,
            messages=_to_openai(messages),
            temperature=self._temperature if temperature is None else temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in resp:
            if chunk.choices and (delta := chunk.choices[0].delta.content):
                yield delta


class OpenAICompatEmbedder:
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        dim: int,
        batch_size: int = 32,
        query_prefix: str = "",
        doc_prefix: str = "",
        timeout_s: float = 120.0,
    ) -> None:
        self.model = model
        self.dim = dim
        self._batch = batch_size
        self._qp, self._dp = query_prefix, doc_prefix
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=1, max=20),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    async def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=self.model, input=batch)
        vectors = [d.embedding for d in sorted(resp.data, key=lambda d: d.index)]
        for v in vectors:
            if len(v) != self.dim:
                raise LLMError(
                    f"Embedding dim mismatch: model returned {len(v)}, EMBED_DIM={self.dim}"
                )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            out.extend(await self._embed_batch([self._dp + t for t in texts[i : i + self._batch]]))
        return out

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed_batch([self._qp + text]))[0]
