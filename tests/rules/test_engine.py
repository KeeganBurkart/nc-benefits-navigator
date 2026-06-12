"""Tests for rules/engine.py — the screening façade.

The engine is a thin orchestrator over the program registry. These tests pin
the JSON/contract shape: program order, household echo, missing-field union,
the exact disclaimer string, and JSON-serializability.
"""
from __future__ import annotations

import json

from rules.engine import DISCLAIMER, ScreeningResult, screen_all
from rules.models import Expenses, Household, IncomeItem, Member

_EXACT_DISCLAIMER = (
    "This is a screening estimate, not an eligibility determination. "
    "Only your county DSS can determine eligibility. "
    "Apply online at https://epass.nc.gov."
)


def _household(**kw):
    base = dict(
        members=[
            Member(
                id="m1",
                age=30,
                relationship="self",
                is_pregnant=False,
                is_disabled=False,
                immigration_status="citizen",
                is_student=False,
            )
        ],
        income=[IncomeItem(id="i1", kind="wages", amount_cents=100000, frequency="monthly")],
        expenses=Expenses(
            rent_or_mortgage_cents=80000,
            utilities_included=False,
            pays_heating_cooling=True,
            dependent_care_cents=0,
            child_support_paid_cents=0,
            medical_expenses_elderly_disabled_cents=0,
        ),
        county="New Hanover",
        purchases_and_prepares_together=True,
    )
    base.update(kw)
    return Household(**base)


def test_returns_screening_result():
    result = screen_all(_household())
    assert isinstance(result, ScreeningResult)


def test_program_order_is_fns_then_medicaid():
    result = screen_all(_household())
    assert [p.program for p in result.programs] == ["fns", "medicaid"]


def test_disclaimer_is_exact_string():
    assert DISCLAIMER == _EXACT_DISCLAIMER
    assert screen_all(_household()).generated_disclaimer == _EXACT_DISCLAIMER


def test_household_is_echoed():
    hh = _household()
    result = screen_all(hh)
    assert result.household == hh
    assert result.household.model_dump() == hh.model_dump()


def test_missing_fields_union_deduped_first_seen():
    # A household missing immigration status: both programs flag the same path,
    # so the union must contain it exactly once.
    hh = Household(
        members=[Member(id="m1", age=10)],
        income=[],
    )
    result = screen_all(hh)
    fns = next(p for p in result.programs if p.program == "fns")
    medicaid = next(p for p in result.programs if p.program == "medicaid")
    assert "members[m1].immigration_status" in fns.missing_fields
    assert "members[m1].immigration_status" in medicaid.missing_fields
    # Union has no duplicates.
    assert len(result.missing_fields) == len(set(result.missing_fields))
    # Every program's missing field appears in the union.
    for path in fns.missing_fields + medicaid.missing_fields:
        assert path in result.missing_fields


def test_missing_fields_first_seen_order_across_programs():
    # FNS flags purchases_and_prepares_together (multi-member) which Medicaid
    # never raises; it should appear in union order after FNS's earlier paths.
    hh = Household(
        members=[Member(id="m1", age=40), Member(id="m2", age=8)],
        income=[],
    )
    result = screen_all(hh)
    fns = next(p for p in result.programs if p.program == "fns")
    # The union begins with FNS's fields in their original relative order.
    fns_in_union = [p for p in result.missing_fields if p in fns.missing_fields]
    assert fns_in_union == fns.missing_fields


def test_empty_household_does_not_raise():
    result = screen_all(Household())
    assert [p.program for p in result.programs] == ["fns", "medicaid"]
    assert all(p.status == "needs_more_info" for p in result.programs)


def test_json_serializable_roundtrip():
    result = screen_all(_household())
    blob = result.model_dump_json()
    parsed = json.loads(blob)
    assert set(parsed) == {"programs", "household", "missing_fields", "generated_disclaimer"}
    assert parsed["generated_disclaimer"] == _EXACT_DISCLAIMER
    assert [p["program"] for p in parsed["programs"]] == ["fns", "medicaid"]
    # model_dump() is also a plain dict structure.
    dumped = result.model_dump()
    assert dumped["programs"][0]["program"] == "fns"


def test_idempotent_dump():
    hh = _household()
    assert screen_all(hh).model_dump() == screen_all(hh).model_dump()
