"""FNS (Food and Nutrition Services / SNAP) eligibility screening for NC.

This is the deterministic domain core. Given a ``Household`` it returns a
``ProgramResult`` with a status, client-readable reasons (each tied to a manual
citation), an estimated monthly benefit when eligible, the documents the
applicant should bring, and any input fields still needed to decide.

It encodes NC's Broad-Based Categorical Eligibility (BBCE) 200% gross income
test, the federal net income test, the standard FY2026 deductions, and the
Thrifty Food Plan allotment formula. All money is integer cents.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package.

NOTE: ``homeless_shelter_deduction_cents`` exists in fns.yaml but is NOT applied
here — homeless households are not modeled in v1 (the shelter-deduction path
assumes a rent/mortgage figure). A future contributor should add a homeless flag
and apply this deduction in _phase_deductions before tackling the net test.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rules.models import Expenses, Household, Member, monthly_cents
from rules.programs._shared import INCOME_DOC_NAMES as _INCOME_DOC_NAMES
from rules.programs._shared import dedup as _dedup
from rules.programs._shared import fmt as _fmt
from rules.programs._shared import reason as _reason
from rules.programs.types import (
    DocumentRequirement,
    IncomeMargin,
    ProgramResult,
    Reason,
)
from rules.tables.loader import load_table

PROGRAM_LABEL = "FNS (Food and Nutrition Services / SNAP)"

_ELDERLY_AGE = 60
_EARNED_KINDS = ("wages", "self_employment")


# ---------------------------------------------------------------------------
# Table lookups (extrapolating beyond size 10)
# ---------------------------------------------------------------------------

def _size_lookup(table_values, size: int) -> int:
    """Look up an int-keyed per-size table, extrapolating past 10.

    The published tables run 1..10. For larger units we add the size-9→10
    increment for each member beyond 10 (USDA's "each additional member"
    method, matching how the YAML itself derived sizes 9-10).
    """
    if size <= 10:
        return int(table_values[size])
    increment = int(table_values[10]) - int(table_values[9])
    return int(table_values[10]) + increment * (size - 10)


def _standard_deduction_band(size: int) -> str:
    if size <= 2:
        return "1-2"
    if size >= 6:
        return "6+"
    return str(size)  # "3", "4", "5"


def _sua_band(size: int) -> str:
    # standard_utility_allowance_cents keys: "1","2","3","4","5+"
    if size >= 5:
        return "5+"
    return str(size)


# ---------------------------------------------------------------------------
# Allotment
# ---------------------------------------------------------------------------

def _allotment(values, size: int, net: int) -> int:
    """Thrifty Food Plan allotment: max − 30% of net, floor 0, with a minimum
    for 1-2 person units when the result is positive. Rounds the 30% half-up."""
    max_allot = _size_lookup(values["max_allotment_cents"], size)
    thirty_pct = int((Decimal(net) * Decimal("0.3")).to_integral_value(rounding=ROUND_HALF_UP))
    allot = max_allot - thirty_pct
    if allot <= 0:
        return 0
    if size <= 2:
        minimum = int(values["minimum_allotment_cents"])
        if allot < minimum:
            return minimum
    return allot


# ---------------------------------------------------------------------------
# Unit composition
# ---------------------------------------------------------------------------

def _is_elderly_or_disabled(m: Member) -> bool:
    elderly = m.age is not None and m.age >= _ELDERLY_AGE
    return bool(elderly or m.is_disabled)


# ---------------------------------------------------------------------------
# Phase helpers — each takes explicit inputs, returns explicit outputs.
# evaluate() calls them in order; reasons are appended in evaluation order
# and the UI renders them in that same order.
# ---------------------------------------------------------------------------

def _phase_unit_composition(household: Household) -> tuple[list[Member], int, list[str], list[Reason]]:
    """Return (unit_members, unit_size, missing, reasons)."""
    members = household.members
    missing: list[str] = []
    reasons: list[Reason] = []

    for m in members:
        if m.immigration_status in (None, "unknown"):
            missing.append(f"members[{m.id}].immigration_status")

    not_qualified = [m for m in members if m.immigration_status == "not_qualified"]
    unit_members = [m for m in members if m.immigration_status != "not_qualified"]
    unit_size = len(unit_members)

    if not_qualified and unit_size > 0:
        reasons.append(_reason(
            "fns.immigration",
            "Some people in this household do not have a qualifying immigration "
            "status, so they are not counted in the household size. Their income "
            "is still counted, which makes this estimate cautious (it may be lower "
            "than the real benefit). The people who do qualify can still get help.",
        ))

    if household.purchases_and_prepares_together is None and len(members) > 1:
        missing.append("purchases_and_prepares_together")
    elif household.purchases_and_prepares_together is False and len(members) > 1:
        reasons.append(_reason(
            "fns.household_composition",
            "You told us this household does not buy and prepare food together. "
            "This early screening still looks at everyone as one group, so the "
            "household size may be larger than it should be and the estimate may "
            "be too high. A caseworker can screen the smaller groups separately.",
        ))

    return unit_members, unit_size, missing, reasons


def _phase_countable_income(household: Household) -> tuple[int, int, bool, list[str]]:
    """Return (gross, earned, income_complete, missing).

    Accumulates gross and earned income; records any incomplete income items.
    """
    gross = 0
    earned = 0
    income_complete = True
    missing: list[str] = []

    for idx, item in enumerate(household.income):
        m = monthly_cents(item)
        if m is None:
            income_complete = False
            if item.amount_cents is None:
                missing.append(f"income[{idx}].amount_cents")
            if item.frequency is None:
                missing.append(f"income[{idx}].frequency")
            if item.frequency == "hourly" and item.hours_per_week is None:
                missing.append(f"income[{idx}].hours_per_week")
            continue
        gross += m
        if item.kind in _EARNED_KINDS:
            earned += m

    return gross, earned, income_complete, missing


def _phase_gross_test(
    values, gross: int, size_for_tables: int, has_elderly_disabled: bool
) -> tuple[bool, list[Reason]]:
    """Return (gross_failed, reasons).

    The elderly/disabled exemption skips the test entirely (never fails).
    """
    reasons: list[Reason] = []

    if has_elderly_disabled:
        reasons.append(_reason(
            "fns.elderly_disabled_exemption",
            "This household has someone who is 60 or older or has a disability, "
            "so it does not have to pass the income-before-deductions test.",
        ))
        return False, reasons

    gross_limit = _size_lookup(values["gross_limit_200pct_cents"], size_for_tables)
    gross_failed = gross > gross_limit

    if not gross_failed:
        reasons.append(_reason(
            "fns.gross_income",
            f"Your household's monthly income before deductions ({_fmt(gross)}) "
            f"is under the limit for a household of {size_for_tables} "
            f"({_fmt(gross_limit)}).",
        ))
    else:
        reasons.append(_reason(
            "fns.gross_income",
            f"Your household's monthly income before deductions ({_fmt(gross)}) "
            f"is over the limit for a household of {size_for_tables} "
            f"({_fmt(gross_limit)}).",
        ))

    reasons.append(_reason(
        "fns.bbce",
        "North Carolina uses a higher income limit (200% of the poverty "
        "level) for food assistance, so more households can qualify.",
    ))

    return gross_failed, reasons


def _phase_deductions(
    values, gross: int, earned: int, size_for_tables: int,
    has_elderly_disabled: bool, exp: Expenses,
) -> tuple[int, bool, list[str], list[Reason]]:
    """Return (total_deductions, shelter_blocked, missing, reasons).

    Applies: standard, earned income, dependent care, child support, medical,
    and excess shelter deductions in that order.
    """
    reasons: list[Reason] = []
    missing: list[str] = []
    deductions = 0

    # Standard deduction (always applies).
    std_band = _standard_deduction_band(size_for_tables)
    std = int(values["standard_deduction_cents"][std_band])
    deductions += std
    reasons.append(_reason(
        "fns.deductions.standard",
        f"A standard deduction of {_fmt(std)} is subtracted from your income.",
    ))

    # 20% earned income deduction.
    if earned > 0:
        pct = Decimal(str(values["earned_income_deduction_pct"]))
        earned_ded = int((Decimal(earned) * pct).to_integral_value(rounding=ROUND_HALF_UP))
        deductions += earned_ded
        reasons.append(_reason(
            "fns.deductions.earned_income",
            f"Because some income is from work, {_fmt(earned_ded)} (20% of earned "
            f"income) is subtracted.",
        ))

    # Dependent care.
    if exp.dependent_care_cents:
        deductions += exp.dependent_care_cents
        reasons.append(_reason(
            "fns.deductions.dependent_care",
            f"Your child or dependent care costs of {_fmt(exp.dependent_care_cents)} "
            f"are subtracted.",
        ))

    # Child support paid.
    if exp.child_support_paid_cents:
        deductions += exp.child_support_paid_cents
        reasons.append(_reason(
            "fns.deductions.child_support",
            f"The {_fmt(exp.child_support_paid_cents)} you pay in child support is "
            f"subtracted.",
        ))

    # Medical (elderly/disabled only, over $35 threshold).
    if has_elderly_disabled and exp.medical_expenses_elderly_disabled_cents:
        threshold = int(values["medical_deduction_threshold_cents"])
        if exp.medical_expenses_elderly_disabled_cents > threshold:
            med = exp.medical_expenses_elderly_disabled_cents - threshold
            deductions += med
            reasons.append(_reason(
                "fns.deductions.medical",
                f"Medical costs above {_fmt(threshold)} for an older or disabled "
                f"household member add a {_fmt(med)} deduction.",
            ))

    # Excess shelter deduction.
    # The net test cannot be completed without rent. If rent is missing we ask
    # for it. If rent is present but pays_heating_cooling is None we can't size
    # the utility allowance, so we ask for that.
    # We only pursue (and demand inputs for) the shelter deduction when the
    # household has actually engaged a housing cost. A household that reported
    # no shelter at all (rent None AND pays_heating_cooling None) gets a $0
    # shelter deduction rather than being blocked for details it never raised.
    shelter_engaged = (
        exp.rent_or_mortgage_cents is not None or exp.pays_heating_cooling is not None
    )
    shelter_blocked = False

    if shelter_engaged:
        if exp.rent_or_mortgage_cents is None:
            # Heating/cooling reported but rent missing — rent is needed for net test.
            missing.append("expenses.rent_or_mortgage_cents")
            shelter_blocked = True
        elif exp.pays_heating_cooling is None:
            missing.append("expenses.pays_heating_cooling")
            shelter_blocked = True
        else:
            shelter = exp.rent_or_mortgage_cents
            if exp.pays_heating_cooling:
                shelter += int(values["standard_utility_allowance_cents"][_sua_band(size_for_tables)])
            income_after_other = max(gross - deductions, 0)
            half = income_after_other // 2
            excess = shelter - half
            if excess > 0:
                if not has_elderly_disabled:
                    cap = int(values["excess_shelter_cap_cents"])
                    excess = min(excess, cap)
                deductions += excess
                reasons.append(_reason(
                    "fns.deductions.shelter",
                    f"Your housing costs are high compared to your income, so a "
                    f"{_fmt(excess)} excess shelter deduction is subtracted.",
                ))

    return deductions, shelter_blocked, missing, reasons


def _phase_net_and_allotment(
    values, gross: int, deductions: int, size_for_tables: int
) -> tuple[str, int | None, list[Reason]]:
    """Return (status, benefit_cents, reasons).

    Computes net income, runs the 100% net test, and computes the allotment
    when the household passes.
    """
    reasons: list[Reason] = []
    net = max(gross - deductions, 0)
    net_limit = _size_lookup(values["net_limit_100pct_cents"], size_for_tables)

    if net <= net_limit:
        reasons.append(_reason(
            "fns.net_income",
            f"Your household's income after deductions ({_fmt(net)}) is under the "
            f"limit for a household of {size_for_tables} ({_fmt(net_limit)}).",
        ))
        benefit = _allotment(values, size_for_tables, net)
        reasons.append(_reason(
            "fns.allotment",
            f"Based on this income, your estimated monthly food benefit is "
            f"{_fmt(benefit)}.",
        ))
        return "likely_eligible", benefit, reasons

    reasons.append(_reason(
        "fns.net_income",
        f"Your household's income after deductions ({_fmt(net)}) is over the limit "
        f"for a household of {size_for_tables} ({_fmt(net_limit)}).",
    ))
    return "likely_ineligible", None, reasons


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def evaluate(household: Household) -> ProgramResult:
    values = load_table("fns").values

    # --- Phase 1: unit composition ---
    unit_members, unit_size, missing, reasons = _phase_unit_composition(household)

    # --- Phase 2: countable income ---
    gross, earned, income_complete, income_missing = _phase_countable_income(household)
    missing.extend(income_missing)

    has_elderly_disabled = any(_is_elderly_or_disabled(m) for m in unit_members)
    documents = _build_documents(household)

    # An empty household (no members, no income) just needs more info.
    if not household.members and not household.income:
        return ProgramResult(
            program="fns",
            program_label=PROGRAM_LABEL,
            status="needs_more_info",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=_dedup(missing),
        )

    # Members exist but none has a qualifying status: the FNS unit is empty,
    # so there is nobody a benefit could be issued to. Deciding on income
    # tables clamped to size 1 would invent a phantom recipient.
    if household.members and unit_size == 0:
        reasons.append(_reason(
            "fns.immigration",
            "No one in this household has an immigration status that qualifies "
            "for FNS, so there is no one who could receive this benefit. Other "
            "programs have different rules — WIC, for example, has no "
            "immigration requirement.",
        ))
        return ProgramResult(
            program="fns",
            program_label=PROGRAM_LABEL,
            status="likely_ineligible",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=[],
        )

    size_for_tables = max(unit_size, 1)

    # Distance-to-limit readout for the test that gates this household: the
    # 200% BBCE gross test, or — since elderly/disabled units skip it — the
    # net test (attached at phase 5, once deductions are known). Informational
    # only; never decides status.
    income_margin: IncomeMargin | None = None
    if income_complete and not has_elderly_disabled:
        gross_limit = _size_lookup(values["gross_limit_200pct_cents"], size_for_tables)
        income_margin = IncomeMargin(
            test_label=(
                f"FNS gross income limit (200% FPL, household of {size_for_tables})"
            ),
            limit_cents=gross_limit,
            income_cents=gross,
            margin_cents=gross_limit - gross,
        )

    # --- Phase 3: gross test ---
    gross_failed, gross_reasons = _phase_gross_test(
        values, gross, size_for_tables, has_elderly_disabled
    )
    reasons.extend(gross_reasons)

    if gross_failed:
        return ProgramResult(
            program="fns",
            program_label=PROGRAM_LABEL,
            status="likely_ineligible",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=[],
            income_margin=income_margin,
        )

    # --- Phase 4: deduction chain ---
    deductions, shelter_blocked, ded_missing, ded_reasons = _phase_deductions(
        values, gross, earned, size_for_tables, has_elderly_disabled, household.expenses
    )
    missing.extend(ded_missing)
    reasons.extend(ded_reasons)

    blocking_missing = _dedup(missing)
    if not income_complete or shelter_blocked or blocking_missing:
        return ProgramResult(
            program="fns",
            program_label=PROGRAM_LABEL,
            status="needs_more_info",
            reasons=reasons,
            estimated_benefit_cents=None,
            required_documents=documents,
            missing_fields=blocking_missing,
            income_margin=income_margin,
        )

    # --- Phase 5: net income test + allotment ---
    status, benefit, net_reasons = _phase_net_and_allotment(values, gross, deductions, size_for_tables)
    reasons.extend(net_reasons)

    if income_complete and has_elderly_disabled:
        # The gross test was waived, so the net test is the one that gates
        # this household; its inputs are only known now, after deductions.
        net = max(gross - deductions, 0)
        net_limit = _size_lookup(values["net_limit_100pct_cents"], size_for_tables)
        income_margin = IncomeMargin(
            test_label=(
                f"FNS net income limit (100% FPL, household of {size_for_tables}; "
                f"gross test waived for age 60+/disability)"
            ),
            limit_cents=net_limit,
            income_cents=net,
            margin_cents=net_limit - net,
        )

    return ProgramResult(
        program="fns",
        program_label=PROGRAM_LABEL,
        status=status,
        reasons=reasons,
        estimated_benefit_cents=benefit,
        required_documents=documents,
        missing_fields=[],
        income_margin=income_margin,
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
            why="You must live in North Carolina to get FNS benefits.",
            rule_id="doc.residency",
        ),
    ]

    # One income doc per distinct income KIND present.
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

    # Expense verification per claimed deduction.
    exp = household.expenses
    if exp.rent_or_mortgage_cents:
        docs.append(DocumentRequirement(
            name="Rent or mortgage statement",
            why="To verify your housing costs for the shelter deduction.",
            rule_id="doc.expenses",
        ))
        if exp.pays_heating_cooling:
            docs.append(DocumentRequirement(
                name="Utility bill",
                why="To verify you pay for heating or cooling.",
                rule_id="doc.expenses",
            ))
    if exp.dependent_care_cents:
        docs.append(DocumentRequirement(
            name="Dependent care receipts",
            why="To verify your child or dependent care costs.",
            rule_id="doc.expenses",
        ))
    if exp.child_support_paid_cents:
        docs.append(DocumentRequirement(
            name="Child support order and payment records",
            why="To verify the child support you are legally required to pay.",
            rule_id="doc.expenses",
        ))
    if exp.medical_expenses_elderly_disabled_cents:
        docs.append(DocumentRequirement(
            name="Medical bills",
            why="To verify medical costs for an older or disabled household member.",
            rule_id="doc.expenses",
        ))

    # Immigration documents when any member is a qualified immigrant.
    if any(m.immigration_status == "qualified_immigrant" for m in household.members):
        docs.append(DocumentRequirement(
            name="Immigration or qualified non-citizen documents",
            why="To verify the immigration status of household members.",
            rule_id="doc.immigration",
        ))

    return docs


