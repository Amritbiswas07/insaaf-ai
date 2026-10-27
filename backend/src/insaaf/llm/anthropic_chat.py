"""Claude via the Anthropic Messages API.

Current-API notes (Claude Opus 5.5 / Sonnet 5.5 / Haiku 5.5):
* Sampling parameters (temperature/top_p/top_k) are not sent — depth and
  spend are controlled with `output_config.effort`.
* Thinking is adaptive and always on, so assistant turns are replayed with
  their original content blocks (thinking + tool_use) via `Message.raw`.
* JSON output uses `output_config.format` (json_schema) when a schema is given.
* `stop_reason == "refusal"` is surfaced as an error; on models that support it
  the server-side refusal fallback is enabled.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic

from insaaf.llm.base import LLMError, LLMResponse, Message, ToolCall, ToolSpec
from insaaf.logs import log

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept `fallbacks: "default"` on the Claude API.
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")
# Adaptive thinking shares max_tokens with the answer; keep headroom.
MIN_MAX_TOKENS = 16_000


def _to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        if m.role == "tool":
            block = {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}
            # All tool results for one assistant turn go in a single user message.
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
            continue
        if m.role == "assistant" and m.raw is not None:
            out.append({"role": "assistant", "content": m.raw})  # verbatim, thinking included
            continue
        if m.role == "assistant" and m.tool_calls:
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            blocks.extend(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                for tc in m.tool_calls
            )
            out.append({"role": "assistant", "content": blocks})
            continue
        if out and out[-1]["role"] == m.role:
            # Merge consecutive same-role turns (e.g. tool results followed by a user nudge).
            prev = out[-1]
            if isinstance(prev["content"], str):
                prev["content"] = [{"type": "text", "text": prev["content"]}]
            prev["content"].append({"type": "text", "text": m.content})
            continue
        out.append({"role": m.role, "content": m.content})
    return "\n\n".join(system_parts), out


class AnthropicChat:
    def __init__(
        self,
        model: str,
        api_key: str,
        timeout_s: float = 180.0,
        effort: str | None = None,
        refusal_fallback: bool = True,
    ) -> None:
        self.model = model
        self._effort = effort
        self._fallback = refusal_fallback and model.startswith(_FALLBACK_MODELS)
        # The SDK retries 408/409/429/5xx and connection errors itself.
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout_s, max_retries=4)

    def _kwargs(
        self,
        messages: list[Message],
        max_tokens: int,
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system, msgs = _to_anthropic(messages)
        output_config: dict[str, Any] = {}
        if self._effort:
            output_config["effort"] = self._effort
        if json_schema:
            output_config["format"] = {"type": "json_schema", "schema": json_schema}
        elif json_mode:
            system += "\n\nRespond with a single JSON object and nothing else."

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max(max_tokens, MIN_MAX_TOKENS),
            "messages": msgs,
        }
        if system:
            kwargs["system"] = system
        if output_config:
            kwargs["output_config"] = output_config
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]
        if self._fallback:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    @property
    def _messages(self) -> Any:
        return self._client.beta.messages if self._fallback else self._client.messages

    async def complete(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSpec] | None = None,
        json_mode: bool = False,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,  # noqa: ARG002 — not supported by current Claude models
        max_tokens: int = 2048,
    ) -> LLMResponse:
        resp = await self._messages.create(
            **self._kwargs(messages, max_tokens, tools, json_mode, json_schema)
        )
        if resp.stop_reason == "refusal":
            category = getattr(resp.stop_details, "category", None) if resp.stop_details else None
            raise LLMError(f"Claude declined the request (category: {category or 'unspecified'})")
        if resp.stop_reason == "max_tokens":
            log.warning("anthropic.max_tokens", model=self.model)
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [
            ToolCall(id=b.id, name=b.name, arguments=dict(b.input or {}))
            for b in resp.content
            if b.type == "tool_use"
        ]
        return LLMResponse(content=text, tool_calls=calls, raw=resp.content)

    async def stream(
        self,
        messages: list[Message],
        *,
        temperature: float | None = None,  # noqa: ARG002
        max_tokens: int = 2048,
    ) -> AsyncIterator[str]:
        async with self._messages.stream(**self._kwargs(messages, max_tokens)) as s:
            async for text in s.text_stream:
                yield text
            final = await s.get_final_message()
        if final.stop_reason == "refusal":
            raise LLMError("Claude declined the request")
