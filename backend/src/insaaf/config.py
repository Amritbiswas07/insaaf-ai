"""Application settings, loaded from environment variables / `.env`.

Every tunable lives here so the same code runs on a laptop (Ollama + local
Mongo/Neo4j) and in production (hosted LLM + managed databases).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- runtime -------------------------------------------------------------
    env: Literal["dev", "prod", "test"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False

    # --- storage -------------------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "insaaf"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr = SecretStr("insaaf-dev-password")
    neo4j_database: str = "neo4j"

    # --- LLM providers ---------------------------------------------------------
    # "openai" covers any OpenAI-compatible server: Ollama (/v1), vLLM, Groq,
    # Together, OpenAI itself. "anthropic" uses the Claude Messages API.
    chat_provider: Literal["openai", "anthropic"] = "openai"
    chat_model: str = "gpt-oss:20b"
    extract_provider: Literal["openai", "anthropic"] = "openai"
    extract_model: str = "llama3.1:8b"

    openai_base_url: str = "http://localhost:11434/v1"
    openai_api_key: SecretStr = SecretStr("ollama")
    anthropic_api_key: SecretStr | None = None
    # Claude: effort replaces sampling params; fallback re-runs refused requests server-side.
    anthropic_chat_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    anthropic_extract_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    anthropic_refusal_fallback: bool = True

    # Embeddings always go through an OpenAI-compatible /embeddings endpoint.
    embed_base_url: str | None = None  # defaults to openai_base_url
    embed_api_key: SecretStr | None = None  # defaults to openai_api_key
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    embed_batch_size: int = 32
    # nomic-embed-text and several BGE/E5 models expect task prefixes.
    embed_query_prefix: str = "search_query: "
    embed_doc_prefix: str = "search_document: "

    llm_timeout_s: float = 180.0
    llm_temperature: float = 0.1

    # --- scraper -------------------------------------------------------------
    kanoon_base_url: str = "https://indiankanoon.org"
    kanoon_api_token: SecretStr | None = None  # official API (api.indiankanoon.org), optional
    scraper_user_agent: str = "InsaafResearchBot/2.0 (+https://github.com/insaaf-ai)"
    scraper_rate_per_s: float = 0.5  # requests per second, global
    scraper_concurrency: int = 2
    scraper_max_retries: int = 4
    scraper_respect_robots: bool = True

    # --- processing ------------------------------------------------------------
    chunk_target_chars: int = 1800
    chunk_overlap_paras: int = 1
    enrich_max_context_chars: int = 24_000

    # --- retrieval / agent -----------------------------------------------------
    retrieval_k: int = 40  # candidates per retriever before fusion
    retrieval_top_cases: int = 8
    rrf_k: int = 60
    authority_weight: float = 0.15  # boost for frequently-cited judgments
    agent_max_steps: int = 6
    agent_mode: Literal["agent", "rag"] = "agent"

    # --- API -----------------------------------------------------------------
    api_keys: list[str] = Field(default_factory=list)  # empty = auth disabled
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
