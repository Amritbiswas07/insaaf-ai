"""LLM enrichment: summary, issues, holding, outcome and principles per judgment.

Instead of truncating at 6,000 characters (which usually cut off the
judgment's conclusion), we build the context by rhetorical role: the opening
facts, every issue, and the court's conclusion are prioritised, then the rest
is filled in up to the budget.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from insaaf.domain import CaseInsights, CaseOutcome, Judgment, Paragraph, RhetoricalRole
from insaaf.llm import ChatLLM, LLMError, Message, parse_json_object
from insaaf.logs import log

SYSTEM = """You are a senior Indian legal analyst. You read court judgments and \
produce precise, neutral, structured case notes. Never invent facts that are not \
in the text. If something is not stated, leave the field empty rather than guessing."""

SCHEMA_HINT = json.dumps(
    {
        "summary": "3-5 sentences: who, what dispute, what the court decided and why",
        "case_type": "e.g. criminal appeal | bail application | writ petition | civil suit | arbitration petition",
        "legal_issues": ["question of law decided"],
        "holding": "1-3 sentences stating what the court held",
        "outcome": "one of: allowed, partly_allowed, dismissed, disposed, remanded, convicted, acquitted, bail_granted, bail_rejected, other",
        "key_principles": ["reusable legal principle stated by the court"],
    },
    indent=2,
)

# Strict JSON Schema for structured output (all keys required, no extras).
INSIGHTS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "case_type": {"type": "string"},
        "legal_issues": {"type": "array", "items": {"type": "string"}},
        "holding": {"type": "string"},
        "outcome": {"type": "string", "enum": [o.value for o in CaseOutcome]},
        "key_principles": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "case_type", "legal_issues", "holding", "outcome", "key_principles"],
    "additionalProperties": False,
}

_PRIORITY = {
    RhetoricalRole.CONCLUSION: 0,
    RhetoricalRole.ISSUE: 1,
    RhetoricalRole.FACTS: 2,
    RhetoricalRole.COURT_DISCOURSE: 3,
    RhetoricalRole.SECTION: 4,
    RhetoricalRole.PETITIONER_ARG: 5,
    RhetoricalRole.RESPONDENT_ARG: 5,
    RhetoricalRole.PRECEDENT: 6,
    RhetoricalRole.OTHER: 7,
}


def select_context(paragraphs: list[Paragraph], budget: int) -> str:
    if sum(len(p.text) for p in paragraphs) <= budget:
        chosen = paragraphs
    else:
        always = {p.idx for p in paragraphs[:3]} | {p.idx for p in paragraphs[-4:]}
        ranked = sorted(
            paragraphs, key=lambda p: (0 if p.idx in always else 1, _PRIORITY.get(p.role, 7), p.idx)
        )
        picked: set[int] = set()
        used = 0
        for p in ranked:
            if used + len(p.text) > budget:
                continue
            picked.add(p.idx)
            used += len(p.text)
        chosen = [p for p in paragraphs if p.idx in picked]

    out, prev = [], -1
    for p in chosen:
        if prev >= 0 and p.idx != prev + 1:
            out.append("[…]")
        tag = f"[{p.role.value}] " if p.role != RhetoricalRole.OTHER else ""
        out.append(f"{tag}{p.text}")
        prev = p.idx
    return "\n\n".join(out)


async def enrich_judgment(llm: ChatLLM, j: Judgment, budget_chars: int = 24_000) -> CaseInsights:
    context = select_context(j.paragraphs, budget_chars)
    user = (
        f"Judgment: {j.title}\nCourt: {j.court or 'unknown'}\nDate: {j.decision_date or 'unknown'}\n"
        f"Bench: {', '.join(j.bench) or 'unknown'}\n\n"
        f"--- JUDGMENT TEXT ---\n{context}\n--- END ---\n\n"
        f"Return a JSON object with exactly these keys:\n{SCHEMA_HINT}"
    )
    messages = [Message("system", SYSTEM), Message("user", user)]

    last_error: Exception | None = None
    for attempt in range(2):
        resp = await llm.complete(
            messages, json_mode=True, json_schema=INSIGHTS_SCHEMA, max_tokens=1500, temperature=0.0
        )
        try:
            return CaseInsights.model_validate(parse_json_object(resp.content))
        except (LLMError, ValidationError) as exc:
            last_error = exc
            log.warning("enrich.invalid_output", doc_id=j.doc_id, attempt=attempt, error=str(exc)[:300])
            messages += [
                Message("assistant", resp.content),
                Message("user", f"That was not valid. Error: {exc}. Return ONLY the corrected JSON object."),
            ]
    raise LLMError(f"Enrichment failed for {j.doc_id}: {last_error}")
