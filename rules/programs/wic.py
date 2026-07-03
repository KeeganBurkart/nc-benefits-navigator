"""WIC (Special Supplemental Nutrition Program for Women, Infants, and
Children) eligibility screening.

Deterministic domain core. WIC has two tests (7 CFR 246.7):

1. Categorical — the household must include a pregnant/postpartum woman, an
   infant, or a child under 5. This screener can see pregnancy and ages, so it
   screens on "any pregnant member or any member under 5"; the postpartum
   window (a recent pregnancy) is a caveat surfaced in the ineligible reason.
2. Income — gross household income at or below 185% of the poverty guidelines,
   counting each pregnant member as one additional household member (the
   unborn child counts toward household size). A household over that limit is
   still income-eligible *adjunctively* if enrolled in Medicaid or SNAP; since
   this tool screens rather than checks enrollment, adjunctive eligibility is
   inferred from this engine's own FNS/Medicaid results and worded as
   contingent on approval.

WIC has NO immigration status requirement, so members are never filtered by
status. WIC provides food packages, not a cash benefit, so
``estimated_benefit_cents`` is always None.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package. All money is integer cents.
"""

from __future__ import annotations

from rules.models import Household, Member, monthly_cents
from rules.programs import fns, medicaid
from rules.programs._shared import INCOME_DOC_NAMES as _INCOME_DOC_NAMES
from rules.programs._shared import dedup, fmt, pct_of_fpl, reason
from rules.programs.types import DocumentRequirement, IncomeMargin, ProgramResult, Reason
from rules.tables.loader import load_table

PROGRAM_LABEL = "WIC"

_CHILD_MAX_AGE = 4  # children under 5 are categorically eligible


def _result(status, reasons, missing, documents, margin=None) -> ProgramResult:
    return ProgramResult(
        program="wic",
        program_label=PROGRAM_LABEL,
        status=status,
        reasons=reasons,
        estimated_benefit_cents=None,
        required_documents=documents,
        missing_fields=dedup(missing),
        income_margin=margin,
    )


def _is_categorical(m: Member) -> bool:
    return bool(m.is_pregnant) or (m.age is not None and m.age <= _CHILD_MAX_AGE)


def _describe(m: Member) -> str:
    if m.is_pregnant:
        return "the pregnant member"
    return f"the {m.age}-year-old child"


def _phase_gross_income(household: Household) -> tuple[int, bool, list[str]]:
    """Return (gross_total, complete, missing). WIC counts every income kind."""
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
    values = load_table("wic").values
    members = household.members
    documents = _build_documents(household)

    if not members and not household.income:
        return _result("needs_more_info", [], [], documents)

    # --- Categorical test: any pregnant member or child under 5 ---
    categorical = [m for m in members if _is_categorical(m)]
    if not categorical:
        unknown: list[str] = []
        for m in members:
            if m.age is None:
                unknown.append(f"members[{m.id}].age")
            if m.is_pregnant is None:
                unknown.append(f"members[{m.id}].is_pregnant")
        if unknown:
            return _result("needs_more_info", [], unknown, documents)
        return _result(
            "likely_ineligible",
            [reason(
                "wic.categorical",
                "No one in the household is pregnant or under age 5, so no one fits "
                "a WIC category. If someone was pregnant within the last year "
                "(postpartum or breastfeeding), they may still qualify — this tool "
                "does not track recent pregnancies, so ask a WIC office.",
            )],
            [],
            documents,
        )

    # --- Income test: gross income vs 185% FPL; pregnant members count as
    # one extra household member each (the unborn child). ---
    inc, complete, income_missing = _phase_gross_income(household)
    if not complete:
        return _result("needs_more_info", [], income_missing, documents)

    pregnant_count = sum(1 for m in members if m.is_pregnant)
    size = max(len(members) + pregnant_count, 1)
    limit = pct_of_fpl(int(values["percent_of_fpl"]), size)

    size_label = (
        f"household of {size}, counting each pregnancy as an extra member"
        if pregnant_count
        else f"household of {size}"
    )
    margin = IncomeMargin(
        test_label=f"WIC income limit (185% FPL, {size_label})",
        limit_cents=limit,
        income_cents=inc,
        margin_cents=limit - inc,
    )

    reasons: list[Reason] = []
    if inc <= limit:
        for m in categorical:
            reasons.append(reason(
                "wic.categorical",
                f"WIC serves pregnant women, infants, and children under 5, so "
                f"{_describe(m)} fits a WIC category.",
            ))
        size_note = (
            " (counting each pregnancy as an extra household member)"
            if pregnant_count else ""
        )
        reasons.append(reason(
            "wic.income",
            f"The household's gross monthly income ({fmt(inc)}) is at or below the "
            f"WIC limit of {fmt(limit)} for this household size{size_note}.",
        ))
        return _result("likely_eligible", reasons, [], documents, margin)

    # Over the 185% limit — adjunctive income eligibility via this engine's own
    # FNS/Medicaid screen (worded as contingent on actual approval).
    if (
        fns.evaluate(household).status == "likely_eligible"
        or medicaid.evaluate(household).status == "likely_eligible"
    ):
        for m in categorical:
            reasons.append(reason(
                "wic.categorical",
                f"WIC serves pregnant women, infants, and children under 5, so "
                f"{_describe(m)} fits a WIC category.",
            ))
        reasons.append(reason(
            "wic.adjunctive",
            f"The household's gross monthly income ({fmt(inc)}) is above the WIC "
            f"limit of {fmt(limit)}, but this screening also found the household "
            f"likely eligible for FNS or Medicaid — and anyone enrolled in those "
            f"programs is automatically income-eligible for WIC. If they are "
            f"approved there, WIC income rules are satisfied.",
        ))
        return _result("likely_eligible", reasons, [], documents, margin)

    reasons.append(reason(
        "wic.income",
        f"The household's gross monthly income ({fmt(inc)}) is above the WIC limit "
        f"of {fmt(limit)} for this household size, and the household did not screen "
        f"as likely eligible for FNS or Medicaid (which would satisfy WIC's income "
        f"rule automatically).",
    ))
    return _result("likely_ineligible", reasons, [], documents, margin)


def _build_documents(household: Household) -> list[DocumentRequirement]:
    docs: list[DocumentRequirement] = [
        DocumentRequirement(
            name="Photo ID or other proof of identity",
            why="We must confirm who is applying.",
            rule_id="doc.identity",
        ),
        DocumentRequirement(
            name="Proof of North Carolina residence",
            why="You must live in North Carolina to get WIC through NC.",
            rule_id="doc.residency",
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
