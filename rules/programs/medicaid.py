"""NC Medicaid (MAGI / Family & Children's) eligibility screening.

This is a deterministic domain core. Given a ``Household`` it screens each
member against NC's MAGI Medicaid coverage groups (children incl. CHIP-level,
pregnant women, parents/caretakers, and the Medicaid Expansion adult group) and
returns a ``ProgramResult``. Medicaid is coverage, not a dollar benefit, so
``estimated_benefit_cents`` is always None.

Eligibility is per-member: the household is ``likely_eligible`` if ANY member
qualifies under any category. ``reasons`` carries one client-readable finding
per member, each tied to a manual citation.

v1 simplifications (each surfaced to the user as a caveat Reason):
- MAGI household size is the whole household (a caseworker confirms the real,
  tax-filing-based Medicaid household).
- The parent/caretaker limit is a documented size-1 percentage approximation of
  NC's dollar-based MAF-C need standard.
- Members age 65+ are out of MAGI scope (aged/blind/disabled Medicaid uses
  different rules this tool does not screen).

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package. All money is integer cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rules.models import Household, Member, monthly_cents
from rules.programs._shared import INCOME_DOC_NAMES as _INCOME_DOC_NAMES
from rules.programs._shared import dedup, fmt, reason
from rules.programs.types import DocumentRequirement, ProgramResult, Reason
from rules.tables.loader import load_table

PROGRAM_LABEL = "NC Medicaid"

# MAGI countable income kinds. SSI and child support received do NOT count
# (asymmetry with FNS, where SSI counts as unearned income).
_COUNTABLE_KINDS = ("wages", "self_employment", "unemployment", "social_security", "ssdi")

_CHILD_MAX_AGE = 18
_ADULT_MIN_AGE = 19
_EXPANSION_MAX_AGE = 64


# ---------------------------------------------------------------------------
# Federal Poverty Level and category limits
# ---------------------------------------------------------------------------

def _fpl_monthly(size: int) -> int:
    """100% FPL monthly cents for a household of ``size`` (>= 1).

    The published chart runs sizes 1..8; beyond 8 we add ``additional_member_cents``
    per extra member (HHS's "each additional person" method).

    ``load_table`` is lru_cached, so this per-call lookup hits memory after the
    first invocation and is both cheap and deterministic.
    """
    fpl = load_table("fpl").values
    by_size = fpl["monthly_cents_by_household_size"]
    if size <= 8:
        return int(by_size[size])
    return int(by_size[8]) + int(fpl["additional_member_cents"]) * (size - 8)


def _limit(base_pct: int, disregard_pct: int, size: int) -> int:
    """Effective monthly income limit = (base + disregard)% of FPL, half-up cents."""
    fpl_monthly = _fpl_monthly(size)
    pct = Decimal(base_pct + disregard_pct)
    return int((Decimal(fpl_monthly) * pct / Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))


def _child_band(age: int) -> str:
    if age < 1:
        return "under_1"
    if age <= 5:
        return "age_1_5"
    return "age_6_18"


# ---------------------------------------------------------------------------
# Member descriptions (no ids in client-facing text)
# ---------------------------------------------------------------------------

def _describe(m: Member) -> str:
    if m.age is None:
        return "an adult in this household"
    if m.age <= _CHILD_MAX_AGE:
        return f"the {m.age}-year-old child"
    if m.is_pregnant:
        return "the pregnant adult"
    return f"the {m.age}-year-old adult"


# ---------------------------------------------------------------------------
# Countable income (household-wide MAGI)
# ---------------------------------------------------------------------------

def _phase_countable_income(household: Household) -> tuple[int, bool, list[str]]:
    """Return (countable_total, complete, missing).

    Only COUNTABLE kinds contribute and can block. Items of non-countable kinds
    (ssi, child_support_received) are irrelevant: a missing amount on one of
    those never blocks the screen.
    """
    total = 0
    complete = True
    missing: list[str] = []

    for idx, item in enumerate(household.income):
        if item.kind not in _COUNTABLE_KINDS:
            continue
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


# ---------------------------------------------------------------------------
# Per-member screening
# ---------------------------------------------------------------------------

class _MemberOutcome:
    """Outcome of screening one member: at most one of eligible/missing fires,
    plus any reason to surface and whether an ABD advisory applies."""

    __slots__ = ("eligible", "reasons", "missing", "is_aged")

    def __init__(self) -> None:
        self.eligible = False
        self.reasons: list[Reason] = []
        self.missing: list[str] = []
        self.is_aged = False


def _screen_member(
    m: Member, inc: int, values, size: int, has_minor: bool
) -> _MemberOutcome:
    out = _MemberOutcome()
    disregard = int(values["magi_disregard_pct"])
    who = _describe(m)

    # Immigration gates.
    if m.immigration_status == "not_qualified":
        out.reasons.append(reason(
            "medicaid.immigration",
            f"Because {who} does not have a qualifying immigration status, they can "
            f"only get Medicaid coverage for a medical emergency, not full coverage. "
            f"This does not affect anyone else in the household.",
        ))
        return out
    if m.immigration_status in (None, "unknown"):
        out.missing.append(f"members[{m.id}].immigration_status")
        return out

    # Cannot categorize without an age.
    if m.age is None:
        out.missing.append(f"members[{m.id}].age")
        return out

    # --- Priority 1: Child (age <= 18) ---
    if m.age <= _CHILD_MAX_AGE:
        band = _child_band(m.age)
        band_limit = _limit(int(values["child_pct_by_age_band"][band]), disregard, size)
        chip_limit = _limit(int(values["child_chip_ceiling_pct"]), disregard, size)
        if inc <= band_limit:
            out.eligible = True
            out.reasons.append(reason(
                "medicaid.child",
                f"Based on the household's monthly income ({fmt(inc)}), {who} likely "
                f"qualifies for children's Medicaid (under the {fmt(band_limit)} limit "
                f"for their age).",
            ))
        elif inc <= chip_limit:
            out.eligible = True
            out.reasons.append(reason(
                "medicaid.child",
                f"With the household's monthly income ({fmt(inc)}), {who} may qualify "
                f"for children's coverage (NC Health Choice/CHIP level), which reaches "
                f"up to {fmt(chip_limit)}.",
            ))
        else:
            out.reasons.append(reason(
                "medicaid.child",
                f"The household's monthly income ({fmt(inc)}) is above the {fmt(chip_limit)} "
                f"limit for children's coverage, so {who} does not appear to qualify.",
            ))
        return out

    # --- Priority 2: Pregnant ---
    pregnant_limit = _limit(int(values["pregnant_pct"]), disregard, size)
    if m.is_pregnant:
        if inc <= pregnant_limit:
            out.eligible = True
            out.reasons.append(reason(
                "medicaid.pregnant",
                f"Based on the household's monthly income ({fmt(inc)}), {who} likely "
                f"qualifies for Medicaid for pregnant women (under the {fmt(pregnant_limit)} "
                f"limit).",
            ))
            return out
        # Pregnant but over the pregnant limit: fall through to parent/expansion.

    # --- Priority 3: Parent / caretaker (adult with a minor in the household) ---
    if m.age >= _ADULT_MIN_AGE and has_minor:
        parent_limit = _limit(int(values["parent_caretaker_pct"]), disregard, size)
        if inc <= parent_limit:
            out.eligible = True
            out.reasons.append(reason(
                "medicaid.parent_caretaker",
                f"As a parent or caretaker living with a child, {who} may qualify for "
                f"Medicaid based on the household's monthly income ({fmt(inc)}). The real "
                f"limit here is a dollar amount that varies by household size, not a simple "
                f"percentage, so a caseworker must confirm it.",
            ))
            return out

    # --- Priority 4: Expansion adult (19-64) ---
    if _ADULT_MIN_AGE <= m.age <= _EXPANSION_MAX_AGE:
        expansion_limit = _limit(int(values["adult_expansion_pct"]), disregard, size)
        if inc <= expansion_limit:
            out.eligible = True
            out.reasons.append(reason(
                "medicaid.expansion_adult",
                f"Based on the household's monthly income ({fmt(inc)}), {who} likely "
                f"qualifies for adult Medicaid (under the {fmt(expansion_limit)} limit).",
            ))
            return out
        # Not eligible via expansion. If pregnancy is unknown and income sits in the
        # window where being pregnant WOULD qualify them, that field is needed.
        if m.is_pregnant is None and expansion_limit < inc <= pregnant_limit:
            out.missing.append(f"members[{m.id}].is_pregnant")
            return out
        out.reasons.append(reason(
            "medicaid.expansion_adult",
            f"The household's monthly income ({fmt(inc)}) is above the {fmt(expansion_limit)} "
            f"limit for adult Medicaid, so {who} does not appear to qualify.",
        ))
        return out

    # --- Priority 5: Age 65+ — out of MAGI scope ---
    if m.age >= 65:
        out.is_aged = True
        out.reasons.append(reason(
            "medicaid.magi_income",
            f"This tool screens income-based (MAGI) Medicaid. Because {who} is 65 or "
            f"older, their coverage is decided under different aged, blind, and disabled "
            f"Medicaid rules that this tool does not screen. They should apply and have a "
            f"caseworker review those rules.",
        ))
        return out

    return out  # unreachable for a well-formed member, but a safe default


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def evaluate(household: Household) -> ProgramResult:
    values = load_table("medicaid").values
    members = household.members
    documents = _build_documents(household)

    # MAGI household size = everyone (v1). Always emit the caveat once.
    size = max(len(members), 1)
    reasons: list[Reason] = []
    missing: list[str] = []

    # --- Countable income (household-wide) ---
    inc, income_complete, income_missing = _phase_countable_income(household)
    missing.extend(income_missing)

    # An empty household just needs more info.
    if not members and not household.income:
        return ProgramResult(
            program="medicaid",
            program_label=PROGRAM_LABEL,
            status="needs_more_info",
            reasons=[],
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=dedup(missing),
        )

    if members:
        reasons.append(reason(
            "medicaid.magi_income",
            "This screening counts everyone in the household as one group and assumes "
            "they file taxes together. The real Medicaid household can be smaller or "
            "larger depending on tax filing, so a caseworker should confirm it.",
        ))

    has_minor = any(m.age is not None and m.age <= _CHILD_MAX_AGE for m in members)

    # --- Fail-fast: if known countable income already exceeds the highest limit
    # ANY member could reach (child CHIP ceiling), no member can qualify. ---
    highest_limit = _limit(
        int(values["child_chip_ceiling_pct"]), int(values["magi_disregard_pct"]), size
    )
    if inc > highest_limit:
        reasons.append(reason(
            "medicaid.magi_income",
            f"The household's monthly income ({fmt(inc)}) is above every Medicaid income "
            f"limit for a household of this size (the highest is {fmt(highest_limit)}), so "
            f"no one in the household appears to qualify for income-based Medicaid.",
        ))
        return ProgramResult(
            program="medicaid",
            program_label=PROGRAM_LABEL,
            status="likely_ineligible",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=[],
        )

    # --- Per-member screening ---
    any_eligible = False
    any_aged = False
    for m in members:
        out = _screen_member(m, inc, values, size, has_minor)
        reasons.extend(out.reasons)
        missing.extend(out.missing)
        if out.eligible:
            any_eligible = True
        if out.is_aged:
            any_aged = True

    blocking_missing = dedup(missing)

    # If countable income is incomplete we cannot declare anyone eligible: the
    # screen ran against an understated income total. Fall through to
    # needs_more_info so the missing income fields are surfaced.
    if any_eligible and income_complete:
        return ProgramResult(
            program="medicaid",
            program_label=PROGRAM_LABEL,
            status="likely_eligible",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=[],
        )

    # No one eligible. Incomplete countable income, a blocking field, or a 65+
    # member this MAGI tool can't screen → needs_more_info (the aged member
    # contributes needs_more_info, not ineligibility).
    if not income_complete or blocking_missing or any_aged:
        return ProgramResult(
            program="medicaid",
            program_label=PROGRAM_LABEL,
            status="needs_more_info",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=blocking_missing,
        )

    # No one eligible, nothing missing → ineligible.
    return ProgramResult(
        program="medicaid",
        program_label=PROGRAM_LABEL,
        status="likely_ineligible",
        reasons=reasons,
        estimated_benefit_cents=None,
        required_documents=documents,
        missing_fields=[],
    )


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def _build_documents(household: Household) -> list[DocumentRequirement]:
    docs: list[DocumentRequirement] = [
        DocumentRequirement(
            name="Photo ID or other proof of identity",
            why="We must confirm who is applying.",
            rule_id="doc.identity",
        ),
        DocumentRequirement(
            name="Proof of North Carolina residence",
            why="You must live in North Carolina to get NC Medicaid.",
            rule_id="doc.residency",
        ),
    ]

    # One income doc per distinct COUNTABLE income kind present.
    seen_kinds: set[str] = set()
    for item in household.income:
        if item.kind not in _COUNTABLE_KINDS or item.kind in seen_kinds:
            continue
        seen_kinds.add(item.kind)
        docs.append(DocumentRequirement(
            name=_INCOME_DOC_NAMES[item.kind],
            why="We need to verify the income reported for this household.",
            rule_id="doc.income",
        ))

    # Immigration documents when any member is a qualified immigrant.
    if any(m.immigration_status == "qualified_immigrant" for m in household.members):
        docs.append(DocumentRequirement(
            name="Immigration or qualified non-citizen documents",
            why="To verify the immigration status of household members.",
            rule_id="doc.immigration",
        ))

    return docs
