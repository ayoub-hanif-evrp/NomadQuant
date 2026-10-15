"""Pydantic models for agent role reports. All text fields are bounded."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
Severity = Literal["low", "medium", "high"]
Verdict = Literal[
    "evidence_supported",
    "insufficient_evidence",
    "verification_failed",
    "research_incomplete",
]
VERDICTS: tuple[str, ...] = (
    "evidence_supported",
    "insufficient_evidence",
    "verification_failed",
    "research_incomplete",
)


class _Report(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Claim(_Report):
    """A numeric claim about a stored backtest that the harness can check."""

    name: ShortText
    value: Decimal
    unit: ShortText = ""
    evidence_ref: ShortText
    window: ShortText | None = None


class Objection(_Report):
    topic: ShortText
    detail: LongText
    severity: Severity = "medium"


class ResearcherReport(_Report):
    task: LongText
    evidence_refs: list[ShortText] = Field(default_factory=list, max_length=50)
    verified_claims: list[Claim] = Field(default_factory=list, max_length=50)
    unverified_claims: list[LongText] = Field(default_factory=list, max_length=50)
    assumptions: list[LongText] = Field(default_factory=list, max_length=50)
    limitations: list[LongText] = Field(default_factory=list, max_length=50)
    questions_for_skeptic: list[LongText] = Field(default_factory=list, max_length=50)


class SkepticReport(_Report):
    objections: list[Objection] = Field(default_factory=list, max_length=50)
    overfitting_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    significance_notes: list[LongText] = Field(default_factory=list, max_length=50)
    cost_notes: list[LongText] = Field(default_factory=list, max_length=50)
    dividend_notes: list[LongText] = Field(default_factory=list, max_length=50)
    look_ahead_notes: list[LongText] = Field(default_factory=list, max_length=50)


class ReviewerReport(_Report):
    verdict: Verdict
    confirmed_findings: list[LongText] = Field(default_factory=list, max_length=50)
    unresolved_objections: list[LongText] = Field(default_factory=list, max_length=50)
    rejected_claims: list[LongText] = Field(default_factory=list, max_length=50)


def schema_hint(model: type[BaseModel]) -> dict[str, object]:
    """JSON schema passed to the provider as a structured output hint."""
    return model.model_json_schema()
