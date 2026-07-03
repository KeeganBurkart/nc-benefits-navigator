"""Adversarial engine tests — deterministic edge cases beyond Hypothesis's bounds.

The property tests generate households of 0..6 members with cents <= 2M; these
tests pin down the extremes and boundaries outside that envelope:

- households larger than the 8-person table rows (FPL extrapolation)
- exact income boundaries (<= limit is eligible; one cent over is not)
- degenerate income (zero-hour hourly wages, fractional hours, astronomical
  amounts) and expenses that dwarf income
- age boundaries (newborn, WIC's 4/5 cutoff, 125)
- structurally odd-but-valid data (dangling income.member_id, every member
  pregnant, sole member without qualifying immigration status)

Every test asserts screen_all completes with valid statuses — crashes here are
real bugs, not test noise.
"""
from __future__ import annotations

from rules.engine import screen_all
from rules.models import Household, IncomeItem, monthly_cents
from rules.programs._shared import pct_of_fpl

_STATUSES = {"likely_eligible", "likely_ineligible", "needs_more_info"}


def _member(mid: str, age: int | None, **overrides) -> dict:
    base = {
        "id": mid,
        "age": age,
        "relationship": "self" if mid == "m1" else "child",
        "is_pregnant": False,
        "is_disabled": False,
        "immigration_status": "citizen",
        "is_student": False,
    }
    base.update(overrides)
    return base


def _income(cents: int, **overrides) -> dict:
    base = {"id": "i1", "member_id": "m1", "kind": "wages", "amount_cents": cents, "frequency": "monthly"}
    base.update(overrides)
    return base


_FULL_EXPENSES = {
    "rent_or_mortgage_cents": 80000,
    "utilities_included": False,
    "pays_heating_cooling": True,
    "dependent_care_cents": 0,
    "child_support_paid_cents": 0,
    "medical_expenses_elderly_disabled_cents": 0,
}


def _full_household(members: list[dict], income: list[dict], **overrides) -> Household:
    data = {
        "members": members,
        "income": income,
        "expenses": _FULL_EXPENSES,
        "county": "Wake",
        "purchases_and_prepares_together": True,
    }
    data.update(overrides)
    return Household.model_validate(data)


def _assert_all_valid(hh: Household) -> dict[str, str]:
    result = screen_all(hh)
    statuses = {p.program: p.status for p in result.programs}
    assert set(statuses) == {"fns", "medicaid", "wic", "lifeline"}
    assert all(s in _STATUSES for s in statuses.values())
    return statuses


# ---------------------------------------------------------------------------
# Household size beyond the published table rows
# ---------------------------------------------------------------------------


def test_twelve_person_household_uses_fpl_extrapolation():
    members = [_member(f"m{i}", 30 if i == 1 else 8) for i in range(1, 13)]
    members[0]["relationship"] = "self"
    members[1]["age"] = 2  # keep one WIC-categorical child
    hh = _full_household(members, [_income(500000)])
    statuses = _assert_all_valid(hh)
    # The size-12 WIC limit must extrapolate past the size-8 row, so the limit
    # grows with each member instead of clamping.
    assert pct_of_fpl(185, 12) > pct_of_fpl(185, 8)
    assert statuses["wic"] == "likely_eligible"  # 5000.00/mo is under the size-12 185% limit


def test_single_member_household_of_one_infant():
    # A newborn with no adults is odd but valid input (kinship placements).
    hh = _full_household([_member("m1", 0, relationship="self")], [_income(0)])
    statuses = _assert_all_valid(hh)
    assert statuses["wic"] == "likely_eligible"  # age 0 is categorical


# ---------------------------------------------------------------------------
# Exact income boundaries (limits are inclusive: <= passes)
# ---------------------------------------------------------------------------


def test_wic_income_exactly_at_limit_is_eligible():
    limit = pct_of_fpl(185, 1)  # 246050 for 2026
    assert limit == 246050
    hh = _full_household([_member("m1", 0, relationship="self")], [_income(limit)])
    assert _assert_all_valid(hh)["wic"] == "likely_eligible"


def test_wic_one_cent_over_limit_falls_through_to_adjunctive():
    hh = _full_household([_member("m1", 0, relationship="self")], [_income(246051)])
    # One cent over the 185% limit: the WIC income test fails, but the infant
    # still screens Medicaid-eligible, so the adjunctive pathway catches it.
    result = screen_all(hh)
    wic = next(p for p in result.programs if p.program == "wic")
    assert wic.status == "likely_eligible"
    assert any(r.rule_id == "wic.adjunctive" for r in wic.reasons)


def test_wic_over_every_pathway_is_ineligible():
    # $3,000/mo for a lone infant clears the 185% WIC limit, the FNS gross
    # limit, and the children's Medicaid limit — no pathway remains.
    hh = _full_household([_member("m1", 0, relationship="self")], [_income(300000)])
    assert _assert_all_valid(hh)["wic"] == "likely_ineligible"


def test_lifeline_income_exactly_at_limit_is_eligible():
    limit = pct_of_fpl(135, 1)
    assert limit == 179550
    hh = _full_household([_member("m1", 40)], [_income(limit)])
    result = screen_all(hh)
    lifeline = next(p for p in result.programs if p.program == "lifeline")
    assert lifeline.status == "likely_eligible"
    assert lifeline.estimated_benefit_cents == 925


def test_lifeline_one_cent_over_falls_back_to_program_pathways():
    hh = _full_household([_member("m1", 40)], [_income(179551)])
    statuses = _assert_all_valid(hh)
    # $1,795.51/mo single adult: over 135% FPL but under the Medicaid expansion
    # limit, so the qualifying-program pathway keeps Lifeline eligible.
    assert statuses["medicaid"] == "likely_eligible"
    assert statuses["lifeline"] == "likely_eligible"


# ---------------------------------------------------------------------------
# Degenerate income
# ---------------------------------------------------------------------------


def test_zero_hour_hourly_wage_counts_as_zero_income():
    item = IncomeItem(id="i1", kind="wages", amount_cents=1500, frequency="hourly", hours_per_week=0)
    assert monthly_cents(item) == 0
    hh = _full_household([_member("m1", 30)], [_income(1500, frequency="hourly", hours_per_week=0)])
    statuses = _assert_all_valid(hh)
    assert statuses["fns"] == "likely_eligible"


def test_fractional_hours_round_half_up():
    # $15.00/hr * 37.5 hrs * 4.33 = $2,435.625 -> 243563 cents (half-up)
    item = IncomeItem(id="i1", kind="wages", amount_cents=1500, frequency="hourly", hours_per_week=37.5)
    assert monthly_cents(item) == 243563


def test_astronomical_income_is_ineligible_everywhere_without_overflow():
    hh = _full_household([_member("m1", 30)], [_income(10**12)])
    statuses = _assert_all_valid(hh)
    assert statuses["fns"] == "likely_ineligible"
    assert statuses["medicaid"] == "likely_ineligible"
    assert statuses["wic"] == "likely_ineligible"
    assert statuses["lifeline"] == "likely_ineligible"


def test_yearly_income_divides_before_comparing():
    # $21,600/yr = $1,800/mo — under the single-adult Medicaid expansion limit,
    # which a naive comparison against the yearly figure would miss.
    hh = _full_household([_member("m1", 30)], [_income(2_160_000, frequency="yearly")])
    assert _assert_all_valid(hh)["medicaid"] == "likely_eligible"


# ---------------------------------------------------------------------------
# Expenses that dwarf income
# ---------------------------------------------------------------------------


def test_rent_far_above_income_caps_shelter_deduction_and_benefit():
    hh = _full_household(
        [_member("m1", 30)],
        [_income(100000)],
        expenses={**_FULL_EXPENSES, "rent_or_mortgage_cents": 10**9},
    )
    result = screen_all(hh)
    fns = next(p for p in result.programs if p.program == "fns")
    assert fns.status == "likely_eligible"
    assert fns.estimated_benefit_cents is not None
    # Benefit can never exceed the size-1 max allotment, and never goes negative.
    assert 0 <= fns.estimated_benefit_cents <= 100000


# ---------------------------------------------------------------------------
# Age boundaries
# ---------------------------------------------------------------------------


def test_wic_child_age_four_in_five_out():
    four = _full_household([_member("m1", 30), _member("m2", 4)], [_income(150000)])
    five = _full_household([_member("m1", 30), _member("m2", 5)], [_income(150000)])
    assert _assert_all_valid(four)["wic"] == "likely_eligible"
    assert _assert_all_valid(five)["wic"] == "likely_ineligible"


def test_age_125_boundary_screens_without_crashing():
    hh = _full_household([_member("m1", 125)], [_income(100000)])
    statuses = _assert_all_valid(hh)
    assert statuses["medicaid"] == "needs_more_info"  # 65+ is an ABD hand-off


# ---------------------------------------------------------------------------
# Structurally odd but valid
# ---------------------------------------------------------------------------


def test_every_member_pregnant_inflates_wic_size_per_pregnancy():
    members = [_member(f"m{i}", 25, is_pregnant=True, relationship="self" if i == 1 else "other_relative")
               for i in range(1, 4)]
    # 3 members + 3 pregnancies = WIC size 6; income between the size-3 and
    # size-6 185% limits proves the pregnancies were counted.
    income_between = pct_of_fpl(185, 3) + 1
    assert income_between <= pct_of_fpl(185, 6)
    hh = _full_household(members, [_income(income_between)])
    assert _assert_all_valid(hh)["wic"] == "likely_eligible"


def test_dangling_income_member_id_still_counts():
    hh = _full_household([_member("m1", 30)], [_income(10**7, member_id="ghost")])
    statuses = _assert_all_valid(hh)
    assert statuses["fns"] == "likely_ineligible"  # the $100k/mo counted despite the dangling ref


def test_sole_member_without_qualified_status_is_ineligible():
    hh = _full_household([_member("m1", 30, immigration_status="not_qualified")], [_income(100000)])
    result = screen_all(hh)
    statuses = {p.program: p.status for p in result.programs}
    # The FNS unit is empty — nobody in this household can receive FNS.
    assert statuses["fns"] == "likely_ineligible"
    fns = next(p for p in result.programs if p.program == "fns")
    assert [r.rule_id for r in fns.reasons] == ["fns.immigration"]
    # The FNS-specific rule must not leak into the other programs: this
    # household's income ($1,000/mo, size 1) is under the WIC and Lifeline
    # limits, and the sole member is 30, so WIC fails only categorically.
    assert statuses["lifeline"] == "likely_eligible"
    assert statuses["wic"] == "likely_ineligible"


def test_sole_member_without_qualified_status_wic_unblocked():
    # WIC has no immigration requirement; the FNS bug must not leak into it.
    hh = _full_household(
        [_member("m1", 30, immigration_status="not_qualified"), _member("m2", 2, immigration_status="not_qualified")],
        [_income(100000)],
    )
    assert _assert_all_valid(hh)["wic"] == "likely_eligible"
