"""FCC Lifeline (phone/internet discount) eligibility screening.

Deterministic domain core. Lifeline is a federal FCC program (47 CFR 54.409):
one discount per household, qualifying either by income (gross household
income at or below 135% of the poverty guidelines) or by a member's
participation in a qualifying program (SNAP, Medicaid, SSI, federal public
housing assistance, or Veterans/Survivors Pension).

This tool screens rather than checks enrollment, so program-based
qualification is inferred two ways:
- An SSI income item on the household IS participation in SSI (the fact that
  income of kind "ssi" was reported means someone receives it).
- This engine's own FNS/Medicaid results, worded as contingent on approval
  ("if approved there, they qualify for Lifeline too").

``estimated_benefit_cents`` is the $9.25/month broadband support amount
(47 CFR 54.403(a)(1)) when likely eligible.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package. All money is integer cents.
"""

from __future__ import annotations

from rules.models import Household, monthly_cents
from rules.programs import fns, medicaid
from rules.programs._shared import INCOME_DOC_NAMES as _INCOME_DOC_NAMES
from rules.programs._shared import dedup, fmt, pct_of_fpl, reason
from rules.programs.types import DocumentRequirement, ProgramResult, Reason
from rules.tables.loader import load_table

PROGRAM_LABEL = "Lifeline (phone/internet discount)"

_ONE_PER_HOUSEHOLD = (
    " Lifeline is limited to one discount per household, and the household "
    "applies through the National Verifier (lifelinesupport.org), not the county DSS."
)


def _result(status, reasons, missing, documents, benefit) -> ProgramResult:
    return ProgramResult(
        program="lifeline",
        program_label=PROGRAM_LABEL,
        status=status,
        reasons=reasons,
        estimated_benefit_cents=benefit,
        required_documents=documents,
        missing_fields=dedup(missing),
    )


def _phase_gross_income(household: Household) -> tuple[int, bool, list[str]]:
    """Return (gross_total, complete, missing). Lifeline counts every income kind."""
    total = 0
    complete = True
    missing: list[str] = []

    for idx, item in enumerate(household.income):
        m = monthly_cents(item)
        if m is None:
            complete = False
            if item.amount_cents is None:
                missing.append(f"income[{idx}].amount_cents")
            if item.frequency is None:
                missing.append(f"income[{idx}].frequency")
            if item.frequency == "hourly" and item.hours_per_week is None:
                missing.append(f"income[{idx}].hours_per_week")
            continue
        total += m

    return total, complete, missing


def evaluate(household: Household) -> ProgramResult:
    values = load_table("lifeline").values
    documents = _build_documents(household)
    discount = int(values["monthly_discount_cents"])

    if not household.members and not household.income:
        return _result("needs_more_info", [], [], documents, None)

    # --- Qualifying program: reported SSI income IS participation in SSI ---
    if any(item.kind == "ssi" for item in household.income):
        return _result(
            "likely_eligible",
            [reason(
                "lifeline.qualifying_program",
                "Someone in the household receives SSI, which is a Lifeline "
                "qualifying program, so the household qualifies for a discount of "
                f"up to {fmt(discount)}/month on phone or internet service."
                + _ONE_PER_HOUSEHOLD,
            )],
            [],
            documents,
            discount,
        )

    # --- Income test: gross income vs 135% FPL ---
    inc, complete, income_missing = _phase_gross_income(household)
    size = max(len(household.members), 1)
    limit = pct_of_fpl(int(values["percent_of_fpl"]), size)

    if complete and inc <= limit:
        return _result(
            "likely_eligible",
            [reason(
                "lifeline.income",
                f"The household's gross monthly income ({fmt(inc)}) is at or below "
                f"the Lifeline limit of {fmt(limit)} for this household size, "
                f"qualifying it for a discount of up to {fmt(discount)}/month on "
                f"phone or internet service." + _ONE_PER_HOUSEHOLD,
            )],
            [],
            documents,
            discount,
        )

    # --- Qualifying program via this engine's own FNS/Medicaid screen ---
    fns_status = fns.evaluate(household).status
    medicaid_status = medicaid.evaluate(household).status
    if fns_status == "likely_eligible" or medicaid_status == "likely_eligible":
        return _result(
            "likely_eligible",
            [reason(
                "lifeline.qualifying_program",
                f"This screening found the household likely eligible for FNS or "
                f"Medicaid — both are Lifeline qualifying programs. If they are "
                f"approved there, the household also qualifies for a discount of up "
                f"to {fmt(discount)}/month on phone or internet service."
                + _ONE_PER_HOUSEHOLD,
            )],
            [],
            documents,
            discount,
        )

    # Not eligible on what we know so far. If the income picture is incomplete,
    # or FNS/Medicaid could still qualify the household, more info is needed
    # (their blocking fields are surfaced by those programs).
    if not complete:
        return _result("needs_more_info", [], income_missing, documents, None)
    if fns_status == "needs_more_info" or medicaid_status == "needs_more_info":
        return _result("needs_more_info", [], [], documents, None)

    reasons: list[Reason] = [reason(
        "lifeline.income",
        f"The household's gross monthly income ({fmt(inc)}) is above the Lifeline "
        f"limit of {fmt(limit)} for this household size, and the household did not "
        f"screen as likely eligible for a qualifying program (FNS, Medicaid, or SSI).",
    )]
    return _result("likely_ineligible", reasons, [], documents, None)


def _build_documents(household: Household) -> list[DocumentRequirement]:
    docs: list[DocumentRequirement] = [
        DocumentRequirement(
            name="Photo ID or other proof of identity",
            why="We must confirm who is applying.",
            rule_id="doc.identity",
        ),
    ]

    seen_kinds: set[str] = set()
    for item in household.income:
        if item.kind is None or item.kind in seen_kinds:
            continue
        seen_kinds.add(item.kind)
        docs.append(DocumentRequirement(
            name=_INCOME_DOC_NAMES[item.kind],
            why="We need to verify the income reported for this household.",
            rule_id="doc.income",
        ))

    return docs
