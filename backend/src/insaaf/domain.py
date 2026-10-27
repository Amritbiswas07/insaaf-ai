"""Core domain models shared by the pipeline, storage, retrieval and API layers."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class RhetoricalRole(StrEnum):
    """Paragraph roles as tagged by Indian Kanoon's `data-structure` attribute."""

    FACTS = "Facts"
    ISSUE = "Issue"
    PETITIONER_ARG = "PetArg"
    RESPONDENT_ARG = "RespArg"
    SECTION = "Section"
    PRECEDENT = "Precedent"
    COURT_DISCOURSE = "CDiscource"  # (sic) — spelled this way in the source HTML
    CONCLUSION = "Conclusion"
    OTHER = "Other"

    @classmethod
    def parse(cls, raw: str | None) -> RhetoricalRole:
        if not raw:
            return cls.OTHER
        try:
            return cls(raw)
        except ValueError:
            return cls.OTHER


class Paragraph(BaseModel):
    idx: int
    role: RhetoricalRole = RhetoricalRole.OTHER
    text: str
    # Indian Kanoon doc ids linked from inside this paragraph (cases or statutes).
    linked_doc_ids: list[str] = Field(default_factory=list)


class LinkedDoc(BaseModel):
    """A hyperlink inside a judgment pointing at another Indian Kanoon document."""

    doc_id: str
    anchor_text: str
    count: int = 1


class StatuteRef(BaseModel):
    """A normalised reference to a section of an Act, e.g. ("IPC", "302")."""

    act: str  # canonical short name, e.g. "IPC", "CrPC", "Constitution"
    section: str | None = None  # "302", "120-B", "21" (article for Constitution)
    act_full_name: str | None = None
    source_doc_id: str | None = None  # IK doc id when resolved from a link

    @property
    def key(self) -> str:
        return f"{self.act}::{self.section}" if self.section else f"{self.act}::*"

    @property
    def label(self) -> str:
        if not self.section:
            return self.act
        prefix = "Article" if self.act == "Constitution" else "Section"
        return f"{prefix} {self.section} {self.act}"


class Party(BaseModel):
    name: str
    role: str  # "petitioner" | "respondent"


class CaseOutcome(StrEnum):
    ALLOWED = "allowed"
    PARTLY_ALLOWED = "partly_allowed"
    DISMISSED = "dismissed"
    DISPOSED = "disposed"
    REMANDED = "remanded"
    CONVICTED = "convicted"
    ACQUITTED = "acquitted"
    BAIL_GRANTED = "bail_granted"
    BAIL_REJECTED = "bail_rejected"
    OTHER = "other"


class CaseInsights(BaseModel):
    """LLM-derived understanding of a judgment (validated structured output)."""

    summary: str = Field(description="Neutral 3-5 sentence summary of the case and decision.")
    case_type: str = Field(description="e.g. criminal appeal, bail application, writ petition, civil suit")
    legal_issues: list[str] = Field(default_factory=list, description="Questions of law the court decided.")
    holding: str = Field(description="What the court held, in 1-3 sentences.")
    outcome: CaseOutcome = CaseOutcome.OTHER
    key_principles: list[str] = Field(
        default_factory=list, description="Reusable legal principles / ratio stated by the court."
    )

    @field_validator("outcome", mode="before")
    @classmethod
    def _coerce_outcome(cls, v: object) -> object:
        if isinstance(v, CaseOutcome) or v is None:
            return v or CaseOutcome.OTHER
        norm = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        if norm in CaseOutcome._value2member_map_:
            return norm
        for needle, outcome in (
            ("partly", CaseOutcome.PARTLY_ALLOWED),
            ("partially", CaseOutcome.PARTLY_ALLOWED),
            ("acquit", CaseOutcome.ACQUITTED),
            ("convict", CaseOutcome.CONVICTED),
            ("remand", CaseOutcome.REMANDED),
            ("bail", CaseOutcome.BAIL_GRANTED if "grant" in norm else CaseOutcome.BAIL_REJECTED),
            ("dismiss", CaseOutcome.DISMISSED),
            ("reject", CaseOutcome.DISMISSED),
            ("allow", CaseOutcome.ALLOWED),
            ("dispos", CaseOutcome.DISPOSED),
        ):
            if needle in norm:
                return outcome
        return CaseOutcome.OTHER

    @field_validator("legal_issues", "key_principles", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> object:
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v or []


class Judgment(BaseModel):
    doc_id: str
    title: str
    url: str
    court: str | None = None
    decision_date: date | None = None
    author: str | None = None
    bench: list[str] = Field(default_factory=list)
    parties: list[Party] = Field(default_factory=list)
    cites_count: int | None = None
    cited_by_count: int | None = None
    paragraphs: list[Paragraph] = Field(default_factory=list)
    links: list[LinkedDoc] = Field(default_factory=list)

    @property
    def year(self) -> int | None:
        return self.decision_date.year if self.decision_date else None

    @property
    def full_text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    idx: int
    text: str
    roles: list[RhetoricalRole]
    para_start: int
    para_end: int


class ProcessingStatus(StrEnum):
    DISCOVERED = "discovered"
    FETCHED = "fetched"
    PARSED = "parsed"
    ENRICHED = "enriched"
    INDEXED = "indexed"
    FAILED = "failed"
    SKIPPED = "skipped"
