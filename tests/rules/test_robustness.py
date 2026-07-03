"""Robustness engine tests — deterministic edge cases beyond Hypothesis's bounds.

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


# ---------------------------------------------------------------------------
# FNS / Medicaid limit boundaries — one cent either side, hand-computed from
# rules/tables/fns.yaml, fpl.yaml, and medicaid.yaml. The arithmetic is in the
# comments; no expected number is copied from engine output.
# ---------------------------------------------------------------------------


def _fns(household: Household):
    return next(p for p in screen_all(household).programs if p.program == "fns")


def _medicaid(household: Household):
    return next(p for p in screen_all(household).programs if p.program == "medicaid")


def _has_reason(result, rule_id: str, *needles: str) -> bool:
    for r in result.reasons:
        if r.rule_id == rule_id and all(n in r.text for n in needles):
            return True
    return False


def _fns_household(member: dict, income: list[dict], expenses: dict):
    """Single-purpose FNS boundary household: exact members/income/expenses,
    no unrelated fields left None that would block the screen."""
    return Household.model_validate({
        "members": [member],
        "income": income,
        "expenses": expenses,
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })


# --- FNS gross income test (200% BBCE), size 1 = 266000 cents ---------------
# Unearned income (social_security) so there is no 20% earned deduction; no
# shelter engaged, so the only deduction is the size-1/2 standard ($209.00).


def test_fns_gross_limit_one_cent_over_is_ineligible():
    # gross 266001 > 266000 (200% size-1 limit) -> fails the gross test outright.
    m = _member("m1", 40)
    hh = _fns_household(m, [_income(266001, kind="social_security")], {})
    fns = _fns(hh)
    assert fns.status == "likely_ineligible"
    assert _has_reason(fns, "fns.gross_income", "over the limit")


def test_fns_gross_limit_exactly_at_limit_passes_gross():
    # gross 266000 == limit -> passes gross; net = 266000 - 20900 (standard) =
    # 245100 > 130500 (net size-1) -> ineligible on NET, not gross.
    m = _member("m1", 40)
    hh = _fns_household(m, [_income(266000, kind="social_security")], {})
    fns = _fns(hh)
    assert fns.status == "likely_ineligible"
    assert _has_reason(fns, "fns.gross_income", "under the limit")
    assert _has_reason(fns, "fns.net_income", "over the limit")


# --- FNS net income test (100%), size 1 = 130500 cents ---------------------
# net = gross - standard(20900); boundary gross for net==130500 is 151400.


def test_fns_net_limit_exactly_at_limit_is_eligible():
    # gross 151400 -> net 151400 - 20900 = 130500 == net limit -> eligible.
    # allotment = 29800 - round_half_up(0.3 * 130500 = 39150) = negative -> $0.
    m = _member("m1", 40)
    hh = _fns_household(m, [_income(151400, kind="social_security")], {})
    fns = _fns(hh)
    assert fns.status == "likely_eligible"
    assert fns.estimated_benefit_cents == 0
    assert _has_reason(fns, "fns.net_income", "under the limit")


def test_fns_net_limit_one_cent_over_is_ineligible():
    # gross 151401 -> net 130501 > 130500 -> ineligible on the net test.
    m = _member("m1", 40)
    hh = _fns_household(m, [_income(151401, kind="social_security")], {})
    fns = _fns(hh)
    assert fns.status == "likely_ineligible"
    assert _has_reason(fns, "fns.net_income", "over the limit")


# --- Elderly/disabled medical deduction threshold = 3500 cents ($35.00) -----
# Applies only to expenses strictly ABOVE $35; a 60+ member makes the household
# elderly (gross-exempt). Income unearned, no shelter engaged.


def test_fns_medical_expense_exactly_at_threshold_gives_no_deduction():
    # medical 3500 is NOT > 3500 -> no medical deduction, no medical reason.
    m = _member("m1", 65)
    hh = _fns_household(
        m,
        [_income(100000, kind="social_security")],
        {"medical_expenses_elderly_disabled_cents": 3500},
    )
    fns = _fns(hh)
    assert fns.status == "likely_eligible"
    assert not any(r.rule_id == "fns.deductions.medical" for r in fns.reasons)


def test_fns_medical_expense_one_cent_over_threshold_deducts_the_excess():
    # medical 3501 > 3500 -> deduction of 3501 - 3500 = 1 cent ($0.01).
    m = _member("m1", 65)
    hh = _fns_household(
        m,
        [_income(100000, kind="social_security")],
        {"medical_expenses_elderly_disabled_cents": 3501},
    )
    fns = _fns(hh)
    assert fns.status == "likely_eligible"
    assert _has_reason(fns, "fns.deductions.medical", "$0.01", "$35.00")


# --- Excess shelter cap = 74400 cents ($744.00): capped for a non-elderly
# household, uncapped when an elderly member is present -------------------
# Size 1, gross 100000 unearned, rent 150000, no heating SUA.
# income_after_other = 100000 - 20900 (standard) = 79100; half = 39550.
# shelter = 150000; excess = 150000 - 39550 = 110450.


def test_fns_excess_shelter_capped_for_non_elderly():
    # Non-elderly: excess 110450 is capped at 74400.
    # net = 100000 - 20900 - 74400 = 4700;
    # allotment = 29800 - round_half_up(0.3 * 4700 = 1410) = 28390.
    m = _member("m1", 40)
    hh = _fns_household(
        m,
        [_income(100000, kind="social_security")],
        {"rent_or_mortgage_cents": 150000, "pays_heating_cooling": False,
         "utilities_included": False},
    )
    fns = _fns(hh)
    assert fns.status == "likely_eligible"
    assert _has_reason(fns, "fns.deductions.shelter", "$744.00")
    assert fns.estimated_benefit_cents == 28390


def test_fns_excess_shelter_uncapped_with_elderly_member():
    # Elderly (age 65): excess 110450 applies uncapped.
    # net = max(100000 - 20900 - 110450, 0) = 0; allotment = 29800 - 0 = 29800.
    m = _member("m1", 65)
    hh = _fns_household(
        m,
        [_income(100000, kind="social_security")],
        {"rent_or_mortgage_cents": 150000, "pays_heating_cooling": False,
         "utilities_included": False},
    )
    fns = _fns(hh)
    assert fns.status == "likely_eligible"
    assert _has_reason(fns, "fns.deductions.shelter", "$1,104.50")
    assert fns.estimated_benefit_cents == 29800


# --- SUA band edge: size 4 uses "4" ($837.00); size 5 uses "5+" ($912.00) ---
# Both non-elderly, gross 200000 unearned, rent 60000, pays heating.
# Size 4: standard "4"=22300; income_after_other=177700; half=88850;
#   shelter = 60000 + 83700 = 143700; excess = 54850 (< 74400 cap, uncapped);
#   net = 200000 - 22300 - 54850 = 122850 (<= 268000 net-4) -> eligible;
#   allotment = 99400 - round_half_up(0.3*122850=36855) = 62545.
# Size 5: standard "5"=26100; income_after_other=173900; half=86950;
#   shelter = 60000 + 91200 = 151200; excess = 64250 (< 74400, uncapped);
#   net = 200000 - 26100 - 64250 = 109650 (<= 313800 net-5) -> eligible;
#   allotment = 118300 - round_half_up(0.3*109650=32895) = 85405.


def _sua_household(n: int):
    members = [_member(f"m{i}", 40) for i in range(1, n + 1)]
    return Household.model_validate({
        "members": members,
        "income": [_income(200000, kind="social_security")],
        "expenses": {"rent_or_mortgage_cents": 60000, "pays_heating_cooling": True,
                     "utilities_included": False},
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })


def test_fns_sua_band_size_four_uses_size_four_allowance():
    fns = _fns(_sua_household(4))
    assert fns.status == "likely_eligible"
    # shelter reason reports the excess: 60000 + 83700(SUA "4") - 88850(half) = 54850.
    assert _has_reason(fns, "fns.deductions.shelter", "$548.50")
    assert fns.estimated_benefit_cents == 62545


def test_fns_sua_band_size_five_uses_five_plus_allowance():
    fns = _fns(_sua_household(5))
    assert fns.status == "likely_eligible"
    # shelter reason reports the excess: 60000 + 91200(SUA "5+") - 86950(half) = 64250.
    assert _has_reason(fns, "fns.deductions.shelter", "$642.50")
    assert fns.estimated_benefit_cents == 85405


# --- Medicaid age-band edges (size 1; disregard 5% applied on top of the
# stored base percentages). fpl_monthly(1) = 133000. -----------------------


def _medicaid_household(age: int, income_cents: int, **member_over):
    m = _member("m1", age, **member_over)
    return Household.model_validate({
        "members": [m],
        "income": [_income(income_cents, kind="wages")],
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })


def test_medicaid_child_band_edge_at_age_six():
    # age_1_5 limit = round(133000 * 146/100) = 194180.
    # age_6_18 limit = round(133000 * 112/100) = 148960.
    # Income 148961 is one cent over the age-6 band but well under CHIP (287280):
    #   age 5 -> children's Medicaid on the 141%+5% band ($1,941.80);
    #   age 6 -> the same income now only reaches CHIP-level coverage.
    five = _medicaid_household(5, 148961)
    six = _medicaid_household(6, 148961)
    assert _medicaid(five).status == "likely_eligible"
    assert _has_reason(_medicaid(five), "medicaid.child", "$1,941.80")
    assert _medicaid(six).status == "likely_eligible"
    # The CHIP-level reason cites the CHIP ceiling: round(133000*216/100)=287280.
    assert _has_reason(_medicaid(six), "medicaid.child", "CHIP", "$2,872.80")


def test_medicaid_child_to_adult_edge_at_age_nineteen():
    # Income 200000: under CHIP ceiling (287280) but over the size-1 expansion
    # limit (round(133000 * 138/100) = 183540).
    #   age 18 -> CHIP-level child coverage -> eligible;
    #   age 19 -> adult expansion only, and 200000 > 183540 -> ineligible.
    eighteen = _medicaid_household(18, 200000, is_pregnant=False)
    nineteen = _medicaid_household(19, 200000, is_pregnant=False)
    assert _medicaid(eighteen).status == "likely_eligible"
    assert _medicaid(nineteen).status == "likely_ineligible"
    assert _has_reason(_medicaid(nineteen), "medicaid.expansion_adult", "does not appear to qualify")


def test_medicaid_expansion_to_abd_edge_at_age_sixty_five():
    # Income 100000 (under the 183540 expansion limit).
    #   age 64 -> expansion adult -> eligible;
    #   age 65 -> out of MAGI scope, ABD hand-off -> needs_more_info.
    sixtyfour = _medicaid_household(64, 100000, is_pregnant=False)
    sixtyfive = _medicaid_household(65, 100000, is_pregnant=False)
    assert _medicaid(sixtyfour).status == "likely_eligible"
    assert _has_reason(_medicaid(sixtyfour), "medicaid.expansion_adult", "likely")
    assert _medicaid(sixtyfive).status == "needs_more_info"
    assert _has_reason(_medicaid(sixtyfive), "medicaid.magi_income", "65 or")
