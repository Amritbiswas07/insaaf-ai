import pytest

from insaaf.agent import LegalAgent, LegalTools, SourceRegistry, citation_report
from insaaf.config import Settings
from insaaf.llm import LLMResponse, ToolCall
from insaaf.retrieval import HybridRetriever, SearchFilters, reciprocal_rank_fusion
from insaaf.retrieval.hybrid import authority_multiplier

from .conftest import FakeEmbedder, FakeGraph, FakeRepo, ScriptedLLM


def test_rrf_rewards_agreement() -> None:
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"]], k=60)
    assert max(scores, key=scores.get) == "b"
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)


def test_authority_multiplier_bounded() -> None:
    assert authority_multiplier(0, 0.15) == 1.0
    assert 1.0 < authority_multiplier(10, 0.15) < authority_multiplier(400, 0.15) <= 1.15
    assert authority_multiplier(10**6, 0.15) == pytest.approx(1.15)


def retriever(settings: Settings) -> HybridRetriever:
    return HybridRetriever(FakeGraph(), FakeEmbedder(), settings)  # type: ignore[arg-type]


async def test_hybrid_search_fuses_and_aggregates(settings: Settings) -> None:
    result = await retriever(settings).search("bail delay")
    ids = [h.case_id for h in result.cases]
    # 111 and 222 appear in both retrievers; 444 only in dense
    assert set(ids[:2]) == {"111", "222"} and ids[-1] == "444"
    top = next(h for h in result.cases if h.case_id == "111")
    assert len(top.passages) == 2
    assert result.precedents and result.precedents[0]["id"] == "999"


async def test_hybrid_search_filters(settings: Settings) -> None:
    result = await retriever(settings).search("bail", SearchFilters(court="bombay", year_from=2000))
    assert [h.case_id for h in result.cases] == ["111"]


def tools(settings: Settings) -> LegalTools:
    graph = FakeGraph()
    return LegalTools(HybridRetriever(graph, FakeEmbedder(), settings), graph, FakeRepo())  # type: ignore[arg-type]


async def test_agent_tool_loop_and_citation_verification(settings: Settings) -> None:
    llm = ScriptedLLM(
        [
            LLMResponse("", [ToolCall("c1", "find_related_cases", {"case_id": "111", "relation": "cites"})]),
            LLMResponse("Bail is the rule [doc:222], applied in [doc:111]. Also [doc:555]."),
        ]
    )
    agent = LegalAgent(llm, tools(settings), max_steps=4)
    events = [e async for e in agent.run("Is delay a ground for bail?")]
    types = [e.type for e in events]
    assert types[0] == "status"
    assert "tool_call" in types and types[-2:] == ["citations", "done"]

    answer = "".join(e.data["text"] for e in events if e.type == "token")
    assert answer.startswith("Bail is the rule [doc:222]")

    cites = next(e.data for e in events if e.type == "citations")
    assert [c["id"] for c in cites["cited"]] == ["222", "111"]
    assert cites["unverified"] == ["555"]  # never retrieved -> flagged

    # retrieval ran before the first model turn and its sources are in the prompt
    first_prompt = llm.calls[0][-1].content
    assert "<sources>" in first_prompt and "[doc:111]" in first_prompt
    # tool result was fed back to the model
    assert any(m.role == "tool" for m in llm.calls[1])


async def test_agent_finalizes_when_budget_exhausted(settings: Settings) -> None:
    loop = LLMResponse("", [ToolCall("x", "search_case_law", {"query": "bail"})])
    llm = ScriptedLLM([loop, loop, LLMResponse("Final [doc:111]")])
    events = [e async for e in LegalAgent(llm, tools(settings), max_steps=2).run("q")]
    done = events[-1]
    assert done.type == "done" and done.data["answer"] == "Final [doc:111]"
    assert done.data["tool_calls"] == 2


async def test_rag_mode_streams(settings: Settings) -> None:
    llm = ScriptedLLM([], stream_text="Answer citing [doc:111]")
    events = [e async for e in LegalAgent(llm, tools(settings), mode="rag").run("q")]
    tokens = [e for e in events if e.type == "token"]
    assert len(tokens) > 1
    assert events[-1].data["answer"].strip() == "Answer citing [doc:111]"


async def test_statute_tool_normalises_input(settings: Settings) -> None:
    out = await tools(settings).run("cases_applying_statute", {"act": "Cr.P.C.", "section": "438"}, SourceRegistry())
    assert "Section 438 CrPC" in out


async def test_tool_errors_are_returned_not_raised(settings: Settings) -> None:
    out = await tools(settings).run("find_related_cases", {"case_id": "1"}, SourceRegistry())
    assert out.startswith("Tool error")


def test_citation_report_dedupes() -> None:
    reg = SourceRegistry()
    reg.add({"id": "1", "title": "A"})
    reg.add({"id": "2", "title": "B"})
    rep = citation_report("x [doc:1] y [doc:1] z [doc:9]", reg)
    assert [c["id"] for c in rep["cited"]] == ["1"]
    assert rep["unverified"] == ["9"]
    assert [c["id"] for c in rep["consulted"]] == ["2"]
