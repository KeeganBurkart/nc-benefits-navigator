"""Tests for the expedited-service advisory and homeless household support.

Hand-computed from rules/tables/fns.yaml (size 1 unless noted):
  gross limit 266000; net limit 130500; std deduction "1-2" 20900;
  max allotment 29800; homeless shelter deduction 19899;
  expedited: gross < 15000 with liquid resources <= 10000, or
  gross + resources < shelter costs.
"""
from __future__ import annotations

from rules.models import Expenses, Household, IncomeItem, Member
from rules.programs.fns import evaluate


def member(id, **kw):
    base = dict(
        age=34,
        relationship="self",
        is_pregnant=False,
        is_disabled=False,
        immigration_status="citizen",
        is_student=False,
    )
    base.update(kw)
    return Member(id=id, **base)


def household(amount_cents=None, **kw):
    income = []
    if amount_cents is not None:
        income = [IncomeItem(id="i1", kind="wages", amount_cents=amount_cents, frequency="monthly")]
    base = dict(
        members=[member("m1")],
        income=income,
        purchases_and_prepares_together=True,
    )
    base.update(kw)
    return Household(**base)


def rule_ids(result):
    return [r.rule_id for r in result.reasons]


def by_rule(result, rule_id):
    return next(r for r in result.reasons if r.rule_id == rule_id)


# ---------------------------------------------------------------------------
# Homeless shelter deduction
# ---------------------------------------------------------------------------

def test_homeless_gets_standard_deduction_and_no_rent_demand():
    # wages 100000: std 20900 + earned 20000 + homeless 19899 = 60799.
    # net = 39201 <= 130500 -> eligible. allotment = 29800 - 0.3*39201 (=11760.3)
    #   = 18039.7 -> whole-dollar floor (FNS-360 step 28) = 18000.
    r = evaluate(household(100000, is_homeless=True))
    assert r.status == "likely_eligible"
    assert r.estimated_benefit_cents == 18000
    assert "fns.deductions.homeless_shelter" in rule_ids(r)
    assert "expenses.rent_or_mortgage_cents" not in r.missing_fields


def test_homeless_skips_rent_based_shelter_path_entirely():
    # pays_heating_cooling True with no rent would normally block on rent;
    # a homeless household must not be blocked and gets no SUA-based excess.
    r = evaluate(household(
        100000, is_homeless=True, expenses=Expenses(pays_heating_cooling=True),
    ))
    assert r.status == "likely_eligible"
    assert "fns.deductions.homeless_shelter" in rule_ids(r)
    assert "fns.deductions.shelter" not in rule_ids(r)
    assert r.missing_fields == []


def test_not_homeless_unchanged():
    # Same household without the flag engages the ordinary path: no homeless
    # deduction, and the pays_heating_cooling-without-rent case still blocks.
    r = evaluate(household(100000, expenses=Expenses(pays_heating_cooling=True)))
    assert r.status == "needs_more_info"
    assert "expenses.rent_or_mortgage_cents" in r.missing_fields
    assert "fns.deductions.homeless_shelter" not in rule_ids(r)


# ---------------------------------------------------------------------------
# Expedited-service advisory
# ---------------------------------------------------------------------------

def test_expedited_definite_when_income_and_resources_tiny():
    # gross 10000 < 15000 and resources 5000 <= 10000 -> definite advisory.
    r = evaluate(household(10000, liquid_resources_cents=5000))
    assert r.status == "likely_eligible"
    text = by_rule(r, "fns.expedited").text
    assert "EXPEDITED" in text and "7 calendar days" in text
    assert "if it also has" not in text  # definite, not conditional


def test_expedited_conditional_when_resources_unknown():
    r = evaluate(household(10000))
    text = by_rule(r, "fns.expedited").text
    assert "ask about" in text and "7 calendar days" in text


def test_expedited_via_shelter_costs_exceeding_income_plus_resources():
    # gross 100000 + resources 20000 = 120000 < rent 150000 (no SUA) -> advisory.
    r = evaluate(household(
        100000,
        liquid_resources_cents=20000,
        expenses=Expenses(rent_or_mortgage_cents=150000, pays_heating_cooling=False),
    ))
    assert r.status == "likely_eligible"
    text = by_rule(r, "fns.expedited").text
    assert "housing costs" in text


def test_expedited_shelter_criterion_silent_when_resources_unknown():
    # Moderate income under shelter costs but unreported resources: stay quiet.
    r = evaluate(household(
        100000,
        expenses=Expenses(rent_or_mortgage_cents=150000, pays_heating_cooling=False),
    ))
    assert "fns.expedited" not in rule_ids(r)


def test_expedited_absent_for_ordinary_household():
    r = evaluate(household(200000, liquid_resources_cents=500000))
    assert "fns.expedited" not in rule_ids(r)


def test_expedited_not_attached_to_ineligible_verdict():
    # Gross test fails before the advisory could ever matter.
    r = evaluate(household(300000, liquid_resources_cents=0))
    assert r.status == "likely_ineligible"
    assert "fns.expedited" not in rule_ids(r)


def test_expedited_attached_to_needs_more_info():
    # Income complete and tiny, but shelter details blocked -> advisory rides
    # along with needs_more_info so the worker sees the 7-day flag early.
    r = evaluate(household(
        10000, liquid_resources_cents=0, expenses=Expenses(pays_heating_cooling=True),
    ))
    assert r.status == "needs_more_info"
    assert "fns.expedited" in rule_ids(r)


def test_zero_income_household_gets_expedited_flag():
    # A member with no income items at all: gross 0 -> conditional advisory.
    r = evaluate(household())
    assert "fns.expedited" in rule_ids(r)
