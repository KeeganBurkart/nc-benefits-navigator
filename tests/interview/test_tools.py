"""Tests for interview.tools: schemas, dollar→cents, dispatch, summary."""

from __future__ import annotations

import json

from interview.tools import (
    _EXPENSE_MONEY,
    TOOLS,
    SessionState,
    compact_screening,
    dispatch,
)
from rules.engine import screen_all
from rules.models import Expenses, Household, IncomeItem, Member

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


def test_tools_export_two_schemas():
    names = {t["name"] for t in TOOLS}
    assert names == {"update_household", "get_screening_status"}


def test_update_household_schema_single_patch_property():
    tool = next(t for t in TOOLS if t["name"] == "update_household")
    props = tool["input_schema"]["properties"]
    assert set(props) == {"patch"}
    assert props["patch"]["type"] == "object"


def test_update_household_description_teaches_model():
    tool = next(t for t in TOOLS if t["name"] == "update_household")
    desc = tool["description"]
    # patch semantics
    assert "_delete" in desc
    assert "merge" in desc.lower() or "merged" in desc.lower()
    # dollars convention, no _cents
    assert "DOLLARS" in desc
    assert "_cents" in desc  # mentions it to forbid it
    # enumerate literal values the model can't read from code
    assert "qualified_immigrant" in desc
    assert "semimonthly" in desc
    assert "self_employment" in desc
    # rejection of unknown fields
    assert "REJECTED" in desc or "rejected" in desc.lower()


def test_get_screening_status_schema_no_input():
    tool = next(t for t in TOOLS if t["name"] == "get_screening_status")
    assert tool["input_schema"]["properties"] == {}


# ---------------------------------------------------------------------------
# Dollar → cents conversion
# ---------------------------------------------------------------------------


def test_income_amount_dollars_to_cents():
    state = SessionState(household=Household(members=[Member(id="m1")]))
    out = dispatch(
        state,
        "update_household",
        {
            "patch": {
                "income": [
                    {"id": "i1", "member_id": "m1", "kind": "wages", "amount": 1250.50, "frequency": "monthly"}
                ]
            }
        },
    )
    parsed = json.loads(out)
    assert "error" not in parsed
    assert state.household.income[0].amount_cents == 125050
    assert state.household.income[0].kind == "wages"


def test_expense_dollar_fields_to_cents():
    state = SessionState()
    out = dispatch(
        state,
        "update_household",
        {
            "patch": {
                "expenses": {
                    "rent_or_mortgage": 800,
                    "dependent_care": 125.25,
                    "child_support_paid": 50,
                    "medical_expenses_elderly_disabled": 33.33,
                }
            }
        },
    )
    assert "error" not in json.loads(out)
    exp = state.household.expenses
    assert exp.rent_or_mortgage_cents == 80000
    assert exp.dependent_care_cents == 12525
    assert exp.child_support_paid_cents == 5000
    assert exp.medical_expenses_elderly_disabled_cents == 3333


def test_no_cents_field_leaks_into_model_via_dollar_name():
    # The model never writes _cents; only the dollar names map through.
    state = SessionState()
    out = dispatch(state, "update_household", {"patch": {"expenses": {"rent_or_mortgage": 1000.99}}})
    assert "error" not in json.loads(out)
    assert state.household.expenses.rent_or_mortgage_cents == 100099


# ---------------------------------------------------------------------------
# Patch applied + screening stored
# ---------------------------------------------------------------------------


def test_patch_applied_and_screening_stored():
    state = SessionState()
    out = dispatch(state, "update_household", {"patch": {"members": [{"id": "m1", "age": 40}]}})
    parsed = json.loads(out)
    assert state.household.members[0].age == 40
    assert state.screening is not None
    # returned JSON carries both household and compact screening
    assert parsed["household"]["members"][0]["age"] == 40
    assert "programs" in parsed["screening"]
    assert "missing_fields" in parsed["screening"]


# ---------------------------------------------------------------------------
# Validation error → error JSON, state unchanged
# ---------------------------------------------------------------------------


def test_unknown_field_returns_error_state_unchanged():
    state = SessionState(household=Household(members=[Member(id="m1", age=30)]))
    before = state.household.model_dump()
    out = dispatch(state, "update_household", {"patch": {"members": [{"id": "m1", "bogus_field": True}]}})
    parsed = json.loads(out)
    assert "error" in parsed
    assert state.household.model_dump() == before  # unchanged
    assert state.screening is None  # never ran


def test_bad_value_returns_error_with_field_path():
    state = SessionState()
    out = dispatch(state, "update_household", {"patch": {"members": [{"id": "m1", "age": 999}]}})
    parsed = json.loads(out)
    assert "error" in parsed
    assert "age" in parsed["error"]


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


def test_unknown_tool_returns_error_json():
    state = SessionState()
    out = dispatch(state, "frobnicate", {})
    parsed = json.loads(out)
    assert "error" in parsed
    assert "frobnicate" in parsed["error"]


# ---------------------------------------------------------------------------
# get_screening_status
# ---------------------------------------------------------------------------


def test_get_screening_status_runs_when_none():
    state = SessionState(household=Household(members=[Member(id="m1")]))
    assert state.screening is None
    out = dispatch(state, "get_screening_status", {})
    parsed = json.loads(out)
    assert "programs" in parsed
    assert "missing_fields" in parsed
    assert state.screening is not None


# ---------------------------------------------------------------------------
# compact_screening shape
# ---------------------------------------------------------------------------


def test_compact_screening_shape():
    screening = screen_all(Household(members=[Member(id="m1")]))
    summary = compact_screening(screening)
    assert set(summary) == {"programs", "missing_fields"}
    prog = summary["programs"][0]
    assert set(prog) == {"program", "label", "status", "reason", "estimated_benefit_cents"}
    assert prog["program"] in ("fns", "medicaid")
    assert isinstance(prog["reason"], str)
    assert summary["missing_fields"] == list(screening.missing_fields)


# ---------------------------------------------------------------------------
# Drift guards — catch model fields added without teaching the model about them
# ---------------------------------------------------------------------------


def test_every_cents_field_in_expenses_has_dollar_key_in_conversion_map():
    """Every *_cents field in Expenses must have a corresponding dollar-named key
    in _EXPENSE_MONEY.  Fails when a contributor adds an Expenses field without
    updating the conversion mapping.
    """
    cents_fields = [
        name for name in Expenses.model_fields if name.endswith("_cents")
    ]
    for cents_field in cents_fields:
        dollar_key = cents_field[: -len("_cents")]
        assert dollar_key in _EXPENSE_MONEY, (
            f"Expenses.{cents_field} has no entry in _EXPENSE_MONEY "
            f"(expected key '{dollar_key}').  Add it to _EXPENSE_MONEY in tools.py "
            f"and document it in _UPDATE_HOUSEHOLD_DESCRIPTION."
        )


def test_every_member_field_mentioned_in_tool_description():
    """Every field of Member (except 'id') must appear by name in the
    update_household tool description so the model knows it exists.
    """
    tool = next(t for t in TOOLS if t["name"] == "update_household")
    desc = tool["description"]
    for field_name in Member.model_fields:
        if field_name == "id":
            continue
        assert field_name in desc, (
            f"Member.{field_name} is not mentioned in the update_household "
            f"tool description.  Add it to _UPDATE_HOUSEHOLD_DESCRIPTION in tools.py."
        )


def test_every_income_field_mentioned_in_tool_description():
    """Every field of IncomeItem (except 'id', 'member_id', 'amount_cents') must
    appear by name in the update_household tool description.  'amount_cents' is
    intentionally hidden from the model (it writes 'amount' in dollars instead).
    """
    tool = next(t for t in TOOLS if t["name"] == "update_household")
    desc = tool["description"]
    # Fields the model must NOT write directly (hidden by dollar-conversion convention).
    hidden = {"id", "member_id", "amount_cents"}
    for field_name in IncomeItem.model_fields:
        if field_name in hidden:
            continue
        assert field_name in desc, (
            f"IncomeItem.{field_name} is not mentioned in the update_household "
            f"tool description.  Add it to _UPDATE_HOUSEHOLD_DESCRIPTION in tools.py."
        )
