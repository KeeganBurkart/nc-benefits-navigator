"""WIC program module unit tests.

Hand-computed limits (2026 FPL monthly cents, 185%):
  size 1: round_half_up(133000 * 1.85) = 246050
  size 2: round_half_up(180333 * 1.85) = 333616
  size 3: round_half_up(227667 * 1.85) = 421184
"""
from __future__ import annotations

from rules.models import Household
from rules.programs.wic import evaluate


def _member(mid: str, age: int | None, *, pregnant: bool | None = False) -> dict:
    return {
        "id": mid,
        "age": age,
        "relationship": "self" if mid == "m1" else "child",
        "is_pregnant": pregnant,
        "is_disabled": False,
        "immigration_status": "citizen",
        "is_student": False,
    }


def _income(cents: int, kind: str = "wages") -> list[dict]:
    return [{"id": "i1", "member_id": "m1", "kind": kind, "amount_cents": cents, "frequency": "monthly"}]


def test_empty_household_needs_more_info():
    result = evaluate(Household())
    assert result.status == "needs_more_info"
    assert result.estimated_benefit_cents is None


def test_child_under_five_and_income_under_limit_is_eligible():
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 3)],
        "income": _income(150000),
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
    assert result.estimated_benefit_cents is None  # WIC is food packages, not cash
    assert result.missing_fields == []
    assert {r.rule_id for r in result.reasons} == {"wic.categorical", "wic.income"}


def test_five_year_old_is_not_categorical():
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 5)],
        "income": _income(150000),
    })
    result = evaluate(hh)
    assert result.status == "likely_ineligible"
    assert result.reasons[0].rule_id == "wic.categorical"


def test_no_categorical_member_is_ineligible_even_with_low_income():
    hh = Household.model_validate({
        "members": [_member("m1", 40)],
        "income": _income(50000),
    })
    result = evaluate(hh)
    assert result.status == "likely_ineligible"
    # The reason points caseworkers at the postpartum window this tool can't see.
    assert "postpartum" in result.reasons[0].text


def test_pregnancy_counts_as_extra_household_member():
    # $2,500/mo: over the size-1 limit (246050) but under size 2 (333616).
    # The pregnancy makes her categorical AND bumps the size to 2.
    hh = Household.model_validate({
        "members": [_member("m1", 27, pregnant=True)],
        "income": _income(250000),
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
    assert any("extra household member" in r.text for r in result.reasons)


def test_unknown_age_or_pregnancy_blocks_categorical_call():
    hh = Household.model_validate({
        "members": [{"id": "m1", "age": None, "is_pregnant": None}],
        "income": _income(100000),
    })
    result = evaluate(hh)
    assert result.status == "needs_more_info"
    assert "members[m1].age" in result.missing_fields
    assert "members[m1].is_pregnant" in result.missing_fields


def test_missing_income_amount_blocks_income_call():
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 2)],
        "income": [{"id": "i1", "kind": "wages", "amount_cents": None, "frequency": "monthly"}],
    })
    result = evaluate(hh)
    assert result.status == "needs_more_info"
    assert "income[0].amount_cents" in result.missing_fields


def test_over_limit_without_other_program_is_ineligible():
    # Size 2 limit 333616; $6,000/mo also fails FNS and Medicaid.
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 3)],
        "income": _income(600000),
        "expenses": {
            "rent_or_mortgage_cents": 100000,
            "utilities_included": False,
            "pays_heating_cooling": True,
            "dependent_care_cents": 0,
            "child_support_paid_cents": 0,
            "medical_expenses_elderly_disabled_cents": 0,
        },
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })
    result = evaluate(hh)
    assert result.status == "likely_ineligible"
    assert result.reasons[-1].rule_id == "wic.income"


def test_adjunctive_eligibility_via_medicaid():
    # $3,500/mo, size 2: over the WIC limit (333616) but the 3-year-old is
    # CHIP-level Medicaid eligible (<= 216% FPL = 389519) -> adjunctive.
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 3)],
        "income": _income(350000),
        "expenses": {
            "rent_or_mortgage_cents": 100000,
            "utilities_included": False,
            "pays_heating_cooling": True,
            "dependent_care_cents": 0,
            "child_support_paid_cents": 0,
            "medical_expenses_elderly_disabled_cents": 0,
        },
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
    assert any(r.rule_id == "wic.adjunctive" for r in result.reasons)
    # Adjunctive wording must be contingent on approval, not a promise.
    adjunctive = next(r for r in result.reasons if r.rule_id == "wic.adjunctive")
    assert "approved" in adjunctive.text


def test_ssi_income_counts_toward_wic_gross():
    # WIC counts every income kind — unlike Medicaid, SSI is not excluded.
    # SSI of $4,000/mo (contrived) puts a size-2 household over 333616, and a
    # household on SSI screens FNS-eligible? No — 400000 > FNS gross 360667 and
    # net limit, and Medicaid excludes SSI so it sees $0 income -> child
    # eligible -> adjunctive keeps WIC likely_eligible. Assert the gross total
    # itself was counted by checking the over-limit figure in the reason text.
    hh = Household.model_validate({
        "members": [_member("m1", 30), _member("m2", 3)],
        "income": _income(400000, kind="ssi"),
        "expenses": {
            "rent_or_mortgage_cents": 100000,
            "utilities_included": False,
            "pays_heating_cooling": True,
            "dependent_care_cents": 0,
            "child_support_paid_cents": 0,
            "medical_expenses_elderly_disabled_cents": 0,
        },
        "county": "Wake",
        "purchases_and_prepares_together": True,
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"  # adjunctive via Medicaid
    adjunctive = next(r for r in result.reasons if r.rule_id == "wic.adjunctive")
    assert "$4,000.00" in adjunctive.text  # gross included the SSI


def test_immigration_status_is_never_a_wic_barrier():
    # A not_qualified child under 5 still fits a WIC category.
    hh = Household.model_validate({
        "members": [
            _member("m1", 30),
            {**_member("m2", 2), "immigration_status": "not_qualified"},
        ],
        "income": _income(150000),
    })
    result = evaluate(hh)
    assert result.status == "likely_eligible"
