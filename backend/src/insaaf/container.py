"""Composition root: builds every long-lived dependency once."""

from __future__ import annotations

from dataclasses import dataclass

from insaaf.agent import LegalAgent, LegalTools
from insaaf.config import Settings
from insaaf.llm import ChatLLM, Embedder, build_chat_llm, build_embedder, build_extract_llm
from insaaf.retrieval import HybridRetriever
from insaaf.storage import GraphStore, MongoRepo


@dataclass
class Container:
    settings: Settings
    repo: MongoRepo
    graph: GraphStore
    embedder: Embedder
    chat_llm: ChatLLM
    retriever: HybridRetriever
    tools: LegalTools

    @classmethod
    def build(cls, s: Settings) -> Container:
        repo = MongoRepo(s.mongo_uri, s.mongo_db)
        graph = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password.get_secret_value(), s.neo4j_database)
        embedder = build_embedder(s)
        retriever = HybridRetriever(graph, embedder, s)
        return cls(
            settings=s,
            repo=repo,
            graph=graph,
            embedder=embedder,
            chat_llm=build_chat_llm(s),
            retriever=retriever,
            tools=LegalTools(retriever, graph, repo),
        )

    def agent(self, mode: str | None = None) -> LegalAgent:
        return LegalAgent(
            self.chat_llm,
            self.tools,
            max_steps=self.settings.agent_max_steps,
            mode=mode or self.settings.agent_mode,
        )

    def extract_llm(self) -> ChatLLM:
        return build_extract_llm(self.settings)

    async def aclose(self) -> None:
        await self.repo.close()
        await self.graph.close()
