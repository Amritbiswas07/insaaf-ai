import json

import pytest

from insaaf.domain import CaseOutcome, Judgment, Paragraph, RhetoricalRole
from insaaf.llm import LLMError, LLMResponse, parse_json_object
from insaaf.processing.chunker import chunk_judgment, embedding_text
from insaaf.processing.enrich import enrich_judgment, select_context

from .conftest import ScriptedLLM


def make_judgment(sizes: list[int]) -> Judgment:
    paras = [
        Paragraph(idx=i, role=RhetoricalRole.FACTS if i == 0 else RhetoricalRole.OTHER, text=("w" * (n - 1)) + ".")
        for i, n in enumerate(sizes)
    ]
    return Judgment(doc_id="1", title="A vs B", url="u", paragraphs=paras)


def test_chunker_covers_every_paragraph_in_order() -> None:
    j = make_judgment([500] * 10)
    chunks = chunk_judgment(j, target_chars=1200, overlap_paras=1)
    covered = set()
    for c in chunks:
        covered.update(range(c.para_start, c.para_end + 1))
        assert len(c.text) <= 1200 + 10
    assert covered == set(range(10))
    assert [c.idx for c in chunks] == list(range(len(chunks)))
    # overlap: each chunk starts on the previous chunk's last paragraph
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.para_start == prev.para_end


def test_chunker_splits_giant_paragraph() -> None:
    sentence = "The court considered the evidence carefully. "
    j = Judgment(doc_id="1", title="t", url="u", paragraphs=[Paragraph(idx=0, text=sentence * 200)])
    chunks = chunk_judgment(j, target_chars=1000, overlap_paras=0)
    assert len(chunks) > 5
    assert all(len(c.text) < 2100 for c in chunks)


def test_embedding_text_has_case_header() -> None:
    j = make_judgment([100])
    c = chunk_judgment(j)[0]
    assert embedding_text(j, c).startswith("A vs B | Facts\n")


def test_select_context_prioritises_conclusion() -> None:
    paras = [Paragraph(idx=i, role=RhetoricalRole.PRECEDENT, text=f"precedent {i} " * 50) for i in range(30)]
    paras[15] = Paragraph(idx=15, role=RhetoricalRole.CONCLUSION, text="FINAL ORDER: appeal dismissed.")
    paras[10] = Paragraph(idx=10, role=RhetoricalRole.ISSUE, text="ISSUE: whether limitation applies.")
    ctx = select_context(paras, budget=4000)
    assert "FINAL ORDER" in ctx and "ISSUE:" in ctx
    assert "[…]" in ctx
    assert len(ctx) < 4500


def test_parse_json_object_lenient() -> None:
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! Here it is: {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    with pytest.raises(LLMError):
        parse_json_object("no json here")


async def test_enrich_repairs_invalid_output() -> None:
    good = {
        "summary": "S.",
        "case_type": "bail application",
        "legal_issues": "whether bail",  # string coerced to list
        "holding": "H.",
        "outcome": "Bail Granted",  # free text coerced to enum
        "key_principles": [],
    }
    llm = ScriptedLLM([LLMResponse("not json"), LLMResponse(json.dumps(good))])
    insights = await enrich_judgment(llm, make_judgment([200, 200]))
    assert insights.outcome is CaseOutcome.BAIL_GRANTED
    assert insights.legal_issues == ["whether bail"]
    assert len(llm.calls) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("dismissed", CaseOutcome.DISMISSED),
        ("Appeal partly allowed", CaseOutcome.PARTLY_ALLOWED),
        ("acquittal upheld", CaseOutcome.ACQUITTED),
        ("bail rejected", CaseOutcome.BAIL_REJECTED),
        ("something else", CaseOutcome.OTHER),
    ],
)
def test_outcome_coercion(raw: str, expected: CaseOutcome) -> None:
    from insaaf.domain import CaseInsights

    assert CaseInsights(summary="s", case_type="t", holding="h", outcome=raw).outcome is expected
