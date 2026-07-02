"""Lifeline program module unit tests.

Hand-computed limits (2026 FPL monthly cents, 135%):
  size 1: round_half_up(133000 * 1.35) = 179550
  size 2: round_half_up(180333 * 1.35) = 243450
"""
from __future__ import annotations

from rules.models import Household
from rules.programs.lifeline import evaluate

_FULL_EXPENSES = {
    "rent_or_mortgage_cents": 100000,
    "utilities_included": False,
    "pays_heating_cooling": True,
    "dependent_care_cents": 0,
    "child_support_paid_cents": 0,
    "medical_expenses_elderly_disabled_cents": 0,
}


def _member(mid: str, age: int) -> dict:
    return {
        "id": mid,
        "age": age,
        "relationship": "self" if mid == "m1" else "child",
        "is_pregnant": False,
        "is_disabled": False,
        "immigration_status": "citizen",
        "is_student": False,
    }


def _income(cents: int, kind: str = "wages") -> list[dict]:
    return [{"id": "i1", "member_id": "m1", "kind": kind, "amount_cents": cents, "frequency": "monthly"}]


def test_empty_household_needs_more_info():
    result = evaluate(Household())
    assert result.status == "needs_more_info"


def test_income_under_135pct_is_eligible_with_discount():
    hh = Household.model_validate({
        "members": [_member("m1", 40)],
        "income": _income(150000),
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
    assert result.estimated_benefit_cents == 925
    assert result.reasons[0].rule_id == "lifeline.income"
    assert "one discount per household" in result.reasons[0].text


def test_ssi_income_item_qualifies_regardless_of_amount():
    # Receiving SSI IS participation in a qualifying program — even an amount
    # that would fail the 135% test on its own.
    hh = Household.model_validate({
        "members": [_member("m1", 40)],
        "income": _income(200000, kind="ssi"),
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
    assert result.reasons[0].rule_id == "lifeline.qualifying_program"
    assert "SSI" in result.reasons[0].text


def test_qualifying_program_pathway_via_medicaid():
    # $3,500/mo size 2: over 135% (243450), FNS fails the net test, but the
    # 3-year-old is CHIP-level Medicaid eligible -> qualifying program.
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 3)],
        "income": _income(350000),
        "expenses": _FULL_EXPENSES,
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
    reason = result.reasons[0]
    assert reason.rule_id == "lifeline.qualifying_program"
    # Wording must be contingent on approval, not a promise of enrollment.
    assert "approved" in reason.text


def test_over_income_and_no_qualifying_program_is_ineligible():
    hh = Household.model_validate({
        "members": [_member("m1", 40)],
        "income": _income(600000),
        "expenses": _FULL_EXPENSES,
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })
    result = evaluate(hh)
    assert result.status == "likely_ineligible"
    assert result.estimated_benefit_cents is None


def test_missing_income_amount_needs_more_info():
    hh = Household.model_validate({
        "members": [_member("m1", 40)],
        "income": [{"id": "i1", "kind": "wages", "amount_cents": None, "frequency": "monthly"}],
    })
    result = evaluate(hh)
    assert result.status == "needs_more_info"
    assert "income[0].amount_cents" in result.missing_fields


def test_undecided_medicaid_holds_lifeline_open():
    # Single adult at $2,000/mo: over the 135% limit (179550), but their
    # immigration status is unknown, so Medicaid (and FNS) can't be decided —
    # a qualifying-program pathway remains open and Lifeline must not close.
    hh = Household.model_validate({
        "members": [{**_member("m1", 30), "immigration_status": None}],
        "income": _income(200000),
        "expenses": _FULL_EXPENSES,
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })
    result = evaluate(hh)
    assert result.status == "needs_more_info"
    # No blocking fields of its own — FNS/Medicaid surface the immigration field.
    assert result.missing_fields == []
