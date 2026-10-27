"""LLM provider factory."""

from __future__ import annotations

from insaaf.config import Settings
from insaaf.llm.base import (
    ChatLLM,
    Embedder,
    LLMError,
    LLMResponse,
    Message,
    ToolCall,
    ToolSpec,
    parse_json_object,
)

__all__ = [
    "ChatLLM",
    "Embedder",
    "LLMError",
    "LLMResponse",
    "Message",
    "ToolCall",
    "ToolSpec",
    "build_chat_llm",
    "build_embedder",
    "build_extract_llm",
    "parse_json_object",
]


def _build(provider: str, model: str, s: Settings, effort: str) -> ChatLLM:
    if provider == "anthropic":
        from insaaf.llm.anthropic_chat import AnthropicChat

        if not s.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is required when a provider is 'anthropic'")
        return AnthropicChat(
            model=model,
            api_key=s.anthropic_api_key.get_secret_value(),
            timeout_s=s.llm_timeout_s,
            effort=effort,
            refusal_fallback=s.anthropic_refusal_fallback,
        )
    from insaaf.llm.openai_compat import OpenAICompatChat

    return OpenAICompatChat(
        model=model,
        base_url=s.openai_base_url,
        api_key=s.openai_api_key.get_secret_value(),
        timeout_s=s.llm_timeout_s,
        temperature=s.llm_temperature,
    )


def build_chat_llm(s: Settings) -> ChatLLM:
    return _build(s.chat_provider, s.chat_model, s, s.anthropic_chat_effort)


def build_extract_llm(s: Settings) -> ChatLLM:
    return _build(s.extract_provider, s.extract_model, s, s.anthropic_extract_effort)


def build_embedder(s: Settings) -> Embedder:
    from insaaf.llm.openai_compat import OpenAICompatEmbedder

    key = s.embed_api_key or s.openai_api_key
    return OpenAICompatEmbedder(
        model=s.embed_model,
        base_url=s.embed_base_url or s.openai_base_url,
        api_key=key.get_secret_value(),
        dim=s.embed_dim,
        batch_size=s.embed_batch_size,
        query_prefix=s.embed_query_prefix,
        doc_prefix=s.embed_doc_prefix,
    )
