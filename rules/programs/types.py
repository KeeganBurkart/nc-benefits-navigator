"""Shared result types for program eligibility modules.

These pydantic models are the binding contract consumed verbatim by the API
and UI layers. A ``ProgramResult`` is what every program module (FNS/SNAP,
NC Medicaid) returns from its ``evaluate(household)`` entry point.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from rules.citations import Citation

Status = Literal["likely_eligible", "likely_ineligible", "needs_more_info"]


class CitationOut(BaseModel):
    """JSON-serializable mirror of the frozen ``Citation`` dataclass.

    Field names are identical to ``Citation`` so the wire shape matches the
    registry exactly. Construct from a ``Citation`` via ``from_citation``.
    """

    model_config = ConfigDict(frozen=True)

    rule_id: str
    manual: str
    section: str
    title: str
    url: str

    @classmethod
    def from_citation(cls, citation: Citation) -> "CitationOut":
        return cls(
            rule_id=citation.rule_id,
            manual=citation.manual,
            section=citation.section,
            title=citation.title,
            url=citation.url,
        )


class Reason(BaseModel):
    """One client-readable explanation tied back to a manual citation."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    text: str
    citation: CitationOut


class DocumentRequirement(BaseModel):
    """A document the applicant should bring to verify the determination."""

    model_config = ConfigDict(frozen=True)

    name: str
    why: str
    rule_id: str


class IncomeMargin(BaseModel):
    """How far the household's counted income sits from the governing income
    limit of the one test named in ``test_label``.

    ``margin_cents = limit_cents - income_cents``: positive means under the
    limit (headroom), negative means over it. This is a caseworker aid for
    spotting households near a benefit cliff — it is informational and never
    decides ``status`` (a household can be under its gross limit yet fail the
    net test, or over WIC's limit yet eligible adjunctively). Only computed
    when the counted income is complete."""

    model_config = ConfigDict(frozen=True)

    test_label: str
    limit_cents: int
    income_cents: int
    margin_cents: int


class ProgramResult(BaseModel):
    """The full screening result for a single program."""

    model_config = ConfigDict(frozen=True)

    program: Literal["fns", "medicaid", "wic", "lifeline"]
    program_label: str
    status: Status
    reasons: list[Reason]
    estimated_benefit_cents: int | None
    required_documents: list[DocumentRequirement]
    missing_fields: list[str]
    income_margin: IncomeMargin | None = None
