"""Tests for rules/models.py — written before implementation (TDD)."""
from decimal import Decimal

import pydantic
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_income(id="i1", amount_cents=None, frequency=None, hours_per_week=None, **kw):
    from rules.models import IncomeItem
    return IncomeItem(
        id=id,
        amount_cents=amount_cents,
        frequency=frequency,
        hours_per_week=hours_per_week,
        **kw,
    )


# ===========================================================================
# 1. Household() from no args is valid and empty
# ===========================================================================

def test_household_default_empty():
    from rules.models import Household
    h = Household()
    assert h.members == []
    assert h.income == []
    assert h.county is None
    assert h.purchases_and_prepares_together is None


def test_expenses_default_empty():
    from rules.models import Expenses
    e = Expenses()
    assert e.rent_or_mortgage_cents is None
    assert e.dependent_care_cents is None


# ===========================================================================
# 2. monthly_cents — one exact test per frequency
# ===========================================================================

def test_monthly_cents_hourly():
    """$15.00/hr × 20h/wk → 1500 * 20 * 4.33 = 129900 cents exactly."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=1500, frequency="hourly", hours_per_week=20.0)
    # 1500 * 20 * 4.33 = 129900.0 — exact, no rounding needed
    assert monthly_cents(item) == 129900


def test_monthly_cents_hourly_rounding():
    """$10.01/hr × 10h/wk: 1001 * 10 * 4.33 = 43343.3 → rounds half-up to 43343."""
    from rules.models import monthly_cents
    # 1001 * 10 = 10010; 10010 * 4.33 = 43343.3 → ROUND_HALF_UP → 43343
    item = make_income(amount_cents=1001, frequency="hourly", hours_per_week=10.0)
    # Decimal truncation: 43343.30 → 43343
    assert monthly_cents(item) == 43343


def test_monthly_cents_weekly():
    """$500/week: 50000 * 4.33 = 216500 exactly."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=50000, frequency="weekly")
    assert monthly_cents(item) == 216500


def test_monthly_cents_weekly_rounding():
    """$300.01/week: 30001 * 4.33 = 129904.33 → rounds half-up to 129904."""
    from rules.models import monthly_cents
    # 30001 * 4.33 = 129904.33 → ROUND_HALF_UP → 129904
    item = make_income(amount_cents=30001, frequency="weekly")
    result = monthly_cents(item)
    expected = int((Decimal("30001") * Decimal("4.33")).to_integral_value(
        rounding="ROUND_HALF_UP"
    ))
    assert result == expected


def test_monthly_cents_biweekly():
    """$1000/biweek: 100000 * 2.17 = 217000 exactly."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=100000, frequency="biweekly")
    assert monthly_cents(item) == 217000


def test_monthly_cents_biweekly_rounding():
    """$1.01 biweekly: 101 * 2.17 = 219.17 → 219."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=101, frequency="biweekly")
    expected = int((Decimal("101") * Decimal("2.17")).to_integral_value(
        rounding="ROUND_HALF_UP"
    ))
    assert monthly_cents(item) == expected  # 219


def test_monthly_cents_semimonthly():
    """$1200/semimonth (twice/month): 120000 * 2 = 240000."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=120000, frequency="semimonthly")
    assert monthly_cents(item) == 240000


def test_monthly_cents_monthly():
    """$2000/month: 200000 * 1 = 200000."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=200000, frequency="monthly")
    assert monthly_cents(item) == 200000


def test_monthly_cents_yearly():
    """$24000/year: 2400000 / 12 = 200000 exactly."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=2400000, frequency="yearly")
    assert monthly_cents(item) == 200000


def test_monthly_cents_yearly_rounding():
    """$1/year: 100 / 12 = 8.333... → rounds half-up to 8."""
    from rules.models import monthly_cents
    item = make_income(amount_cents=100, frequency="yearly")
    expected = int((Decimal("100") / Decimal("12")).to_integral_value(
        rounding="ROUND_HALF_UP"
    ))
    assert monthly_cents(item) == expected  # 8


# ===========================================================================
# 3. monthly_cents returns None for missing data
# ===========================================================================

def test_monthly_cents_none_when_amount_missing():
    from rules.models import monthly_cents
    item = make_income(amount_cents=None, frequency="monthly")
    assert monthly_cents(item) is None


def test_monthly_cents_none_when_frequency_missing():
    from rules.models import monthly_cents
    item = make_income(amount_cents=100000, frequency=None)
    assert monthly_cents(item) is None


def test_monthly_cents_none_when_hourly_without_hours():
    from rules.models import monthly_cents
    item = make_income(amount_cents=1500, frequency="hourly", hours_per_week=None)
    assert monthly_cents(item) is None


# ===========================================================================
# 4. apply_patch
# ===========================================================================

def base_household():
    from rules.models import Expenses, Household, IncomeItem, Member
    return Household(
        members=[
            Member(id="m1", age=30, relationship="self"),
            Member(id="m2", age=5, relationship="child"),
        ],
        income=[
            IncomeItem(id="i1", member_id="m1", kind="wages", amount_cents=200000, frequency="monthly"),
        ],
        expenses=Expenses(rent_or_mortgage_cents=80000, dependent_care_cents=30000),
        county="New Hanover",
        purchases_and_prepares_together=True,
    )


def test_apply_patch_scalar_overwrite():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"county": "Wake"})
    assert h2.county == "Wake"


def test_apply_patch_explicit_null_clears():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"county": None})
    assert h2.county is None


def test_apply_patch_member_update_by_id():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"members": [{"id": "m1", "age": 31}]})
    m1 = next(m for m in h2.members if m.id == "m1")
    assert m1.age == 31
    assert m1.relationship == "self"  # unchanged


def test_apply_patch_member_append_new_id():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"members": [{"id": "m3", "age": 10, "relationship": "child"}]})
    ids = [m.id for m in h2.members]
    assert "m3" in ids
    assert len(h2.members) == 3


def test_apply_patch_member_delete():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"members": [{"id": "m2", "_delete": True}]})
    ids = [m.id for m in h2.members]
    assert "m2" not in ids
    assert len(h2.members) == 1


def test_apply_patch_income_update_by_id():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"income": [{"id": "i1", "amount_cents": 250000}]})
    i1 = next(i for i in h2.income if i.id == "i1")
    assert i1.amount_cents == 250000
    assert i1.frequency == "monthly"  # unchanged


def test_apply_patch_income_append_new_id():
    from rules.models import apply_patch
    h = base_household()
    patch = {"income": [{"id": "i2", "kind": "unemployment", "amount_cents": 50000, "frequency": "weekly"}]}
    h2 = apply_patch(h, patch)
    ids = [i.id for i in h2.income]
    assert "i2" in ids
    assert len(h2.income) == 2


def test_apply_patch_income_delete():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"income": [{"id": "i1", "_delete": True}]})
    assert len(h2.income) == 0


def test_apply_patch_expenses_field_merge():
    from rules.models import apply_patch
    h = base_household()
    h2 = apply_patch(h, {"expenses": {"dependent_care_cents": 50000}})
    assert h2.expenses.rent_or_mortgage_cents == 80000  # unchanged
    assert h2.expenses.dependent_care_cents == 50000


def test_apply_patch_immutability():
    """Input household must not be mutated."""
    from rules.models import apply_patch
    h = base_household()
    original_county = h.county
    apply_patch(h, {"county": "Durham"})
    assert h.county == original_county


def test_apply_patch_result_is_validated():
    """Patch with invalid value raises ValidationError."""
    from rules.models import apply_patch
    h = base_household()
    with pytest.raises(pydantic.ValidationError):
        apply_patch(h, {"income": [{"id": "i1", "amount_cents": -1}]})


# ===========================================================================
# 5. Validation errors
# ===========================================================================

def test_negative_amount_cents_raises():
    from rules.models import IncomeItem
    with pytest.raises(pydantic.ValidationError) as exc_info:
        IncomeItem(id="i1", amount_cents=-100)
    assert "amount_cents" in str(exc_info.value)


def test_age_400_raises():
    from rules.models import Member
    with pytest.raises(pydantic.ValidationError) as exc_info:
        Member(id="m1", age=400)
    assert "age" in str(exc_info.value)


def test_negative_expense_raises():
    from rules.models import Expenses
    with pytest.raises(pydantic.ValidationError):
        Expenses(rent_or_mortgage_cents=-1)


# ===========================================================================
# 6. missing_summary
# ===========================================================================

def test_missing_summary_empty_household():
    from rules.models import Household, missing_summary
    h = Household()
    result = missing_summary(h)
    # top-level scalars: county, purchases_and_prepares_together
    assert "county" in result
    assert "purchases_and_prepares_together" in result


def test_missing_summary_member_paths():
    from rules.models import Household, Member, missing_summary
    h = Household(members=[Member(id="m1")])
    result = missing_summary(h)
    assert "members[m1].age" in result
    assert "members[m1].relationship" in result
    assert "members[m1].is_pregnant" in result
    assert "members[m1].is_disabled" in result
    assert "members[m1].immigration_status" in result
    assert "members[m1].is_student" in result


def test_missing_summary_income_paths_use_index():
    from rules.models import Household, IncomeItem, missing_summary
    h = Household(income=[IncomeItem(id="i1")])
    result = missing_summary(h)
    # income uses index, not id
    assert "income[0].kind" in result
    assert "income[0].amount_cents" in result
    assert "income[0].frequency" in result
    # member_id always excluded
    assert "income[0].member_id" not in result


def test_missing_summary_income_excludes_hours_when_not_hourly():
    from rules.models import Household, IncomeItem, missing_summary
    h = Household(income=[IncomeItem(id="i1", frequency="monthly", amount_cents=100000)])
    result = missing_summary(h)
    assert "income[0].hours_per_week" not in result


def test_missing_summary_income_includes_hours_when_hourly():
    from rules.models import Household, IncomeItem, missing_summary
    h = Household(income=[IncomeItem(id="i1", frequency="hourly", amount_cents=1500)])
    result = missing_summary(h)
    assert "income[0].hours_per_week" in result


def test_missing_summary_expenses_conditional_exclusion():
    from rules.models import Expenses, Household, missing_summary
    # Without rent set, utilities_included and pays_heating_cooling excluded
    h = Household(expenses=Expenses())
    result = missing_summary(h)
    assert "expenses.utilities_included" not in result
    assert "expenses.pays_heating_cooling" not in result


def test_missing_summary_expenses_includes_heat_when_rent_set():
    from rules.models import Expenses, Household, missing_summary
    h = Household(expenses=Expenses(rent_or_mortgage_cents=80000))
    result = missing_summary(h)
    assert "expenses.utilities_included" in result
    assert "expenses.pays_heating_cooling" in result


def test_missing_summary_expenses_path_format():
    from rules.models import Expenses, Household, missing_summary
    h = Household(expenses=Expenses())
    result = missing_summary(h)
    assert "expenses.rent_or_mortgage_cents" in result
    assert "expenses.dependent_care_cents" in result
    assert "expenses.child_support_paid_cents" in result
    assert "expenses.medical_expenses_elderly_disabled_cents" in result


def test_missing_summary_no_false_positives():
    """Filled-in fields should NOT appear in missing_summary."""
    from rules.models import Expenses, Household, Member, missing_summary
    h = Household(
        members=[Member(id="m1", age=30, relationship="self", is_pregnant=False,
                        is_disabled=False, immigration_status="citizen", is_student=False)],
        expenses=Expenses(
            rent_or_mortgage_cents=80000,
            utilities_included=True,
            pays_heating_cooling=True,
            dependent_care_cents=0,
            child_support_paid_cents=0,
            medical_expenses_elderly_disabled_cents=0,
        ),
        county="Wake",
        purchases_and_prepares_together=True,
    )
    result = missing_summary(h)
    assert "members[m1].age" not in result
    assert "members[m1].relationship" not in result
    assert "county" not in result
    assert "expenses.rent_or_mortgage_cents" not in result


def test_missing_summary_stable_order():
    """missing_summary returns fields in document order."""
    from rules.models import Household, Member, missing_summary
    h = Household(
        members=[Member(id="m1")],
        county=None,
    )
    result = missing_summary(h)
    # All member fields come before top-level scalars (members declared before county in Household)
    # Within member: age before relationship, etc.
    member_fields = [r for r in result if r.startswith("members[m1].")]
    assert member_fields == [
        "members[m1].age",
        "members[m1].relationship",
        "members[m1].is_pregnant",
        "members[m1].is_disabled",
        "members[m1].immigration_status",
        "members[m1].is_student",
    ]
