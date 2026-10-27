"""Paragraph-aware chunking that never splits mid-paragraph unless it must."""

from __future__ import annotations

import re

from insaaf.domain import Chunk, Judgment, Paragraph, RhetoricalRole

_SENTENCE = re.compile(r"(?<=[.;:?!])\s+(?=[A-Z(\"'])")


def _split_long(p: Paragraph, target: int) -> list[Paragraph]:
    if len(p.text) <= target * 2:
        return [p]
    parts, buf = [], ""
    for sent in _SENTENCE.split(p.text):
        if buf and len(buf) + len(sent) > target:
            parts.append(buf.strip())
            buf = ""
        buf += sent + " "
    if buf.strip():
        parts.append(buf.strip())
    return [p.model_copy(update={"text": t}) for t in parts]


def chunk_judgment(j: Judgment, target_chars: int = 1800, overlap_paras: int = 1) -> list[Chunk]:
    pieces: list[Paragraph] = [piece for p in j.paragraphs for piece in _split_long(p, target_chars)]
    chunks: list[Chunk] = []
    i = 0
    while i < len(pieces):
        start = i
        size = 0
        while i < len(pieces) and (size == 0 or size + len(pieces[i].text) <= target_chars):
            size += len(pieces[i].text) + 2
            i += 1
        group = pieces[start:i]
        roles = list(dict.fromkeys(p.role for p in group if p.role != RhetoricalRole.OTHER))
        chunks.append(
            Chunk(
                chunk_id=f"{j.doc_id}:{len(chunks)}",
                doc_id=j.doc_id,
                idx=len(chunks),
                text="\n\n".join(p.text for p in group),
                roles=roles or [RhetoricalRole.OTHER],
                para_start=group[0].idx,
                para_end=group[-1].idx,
            )
        )
        if i < len(pieces) and overlap_paras > 0:
            i = max(start + 1, i - overlap_paras)
    return chunks


def embedding_text(j: Judgment | dict, chunk: Chunk) -> str:
    """Prefix chunks with case context so retrieval can match on title/court too."""
    if isinstance(j, dict):
        title, court, decided = j.get("title"), j.get("court"), j.get("decision_date")
    else:
        title, court, decided = j.title, j.court, j.decision_date
    roles = ", ".join(r.value for r in chunk.roles if r != RhetoricalRole.OTHER)
    header = " | ".join(str(x) for x in (title, court, decided, roles) if x)
    return f"{header}\n{chunk.text}"
