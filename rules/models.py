"""Household data models for NC Benefits Navigator rules engine.

This module is pure deterministic logic — it must never import from
interview/, server/, or the anthropic package.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

class Member(BaseModel):
    id: str
    age: int | None = None
    relationship: Literal["self", "spouse", "child", "other_relative", "unrelated"] | None = None
    is_pregnant: bool | None = None
    # receives disability-based benefit or meets program disability standard
    is_disabled: bool | None = None
    immigration_status: Literal["citizen", "qualified_immigrant", "not_qualified", "unknown"] | None = None
    is_student: bool | None = None

    @field_validator("age")
    @classmethod
    def age_bounds(cls, v: int | None) -> int | None:
        if v is not None and not (0 <= v <= 125):
            raise ValueError("age must be between 0 and 125 inclusive")
        return v


# ---------------------------------------------------------------------------
# IncomeItem
# ---------------------------------------------------------------------------

class IncomeItem(BaseModel):
    id: str  # required — needed for list merging
    member_id: str | None = None
    kind: Literal[
        "wages",
        "self_employment",
        "unemployment",
        "ssi",
        "ssdi",
        "social_security",
        "child_support_received",
        "other",
    ] | None = None
    amount_cents: int | None = None
    frequency: Literal[
        "hourly", "weekly", "biweekly", "semimonthly", "monthly", "yearly"
    ] | None = None
    # used only when frequency is hourly
    hours_per_week: float | None = None

    @field_validator("amount_cents")
    @classmethod
    def amount_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("amount_cents must be >= 0")
        return v


# ---------------------------------------------------------------------------
# Expenses (all fields monthly, all int | None, money fields >= 0)
# ---------------------------------------------------------------------------

class Expenses(BaseModel):
    rent_or_mortgage_cents: int | None = None
    utilities_included: bool | None = None
    pays_heating_cooling: bool | None = None
    dependent_care_cents: int | None = None
    child_support_paid_cents: int | None = None
    medical_expenses_elderly_disabled_cents: int | None = None

    @field_validator(
        "rent_or_mortgage_cents",
        "dependent_care_cents",
        "child_support_paid_cents",
        "medical_expenses_elderly_disabled_cents",
    )
    @classmethod
    def money_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("expense field must be >= 0")
        return v


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------

class Household(BaseModel):
    members: list[Member] = []
    income: list[IncomeItem] = []
    expenses: Expenses = Expenses()
    county: str | None = None
    purchases_and_prepares_together: bool | None = None


# ---------------------------------------------------------------------------
# monthly_cents
# ---------------------------------------------------------------------------

def monthly_cents(item: IncomeItem) -> int | None:
    """Return the monthly equivalent of an income item in cents.

    Returns None if amount_cents or frequency is missing, or if frequency is
    hourly but hours_per_week is missing.

    Normalization multipliers (using Decimal for exact rounding):
      hourly      → amount * hours_per_week * 4.33
      weekly      → amount * 4.33
      biweekly    → amount * 2.17
      semimonthly → amount * 2
      monthly     → amount * 1
      yearly      → amount / 12
    """
    if item.amount_cents is None or item.frequency is None:
        return None

    amount = Decimal(item.amount_cents)

    if item.frequency == "hourly":
        if item.hours_per_week is None:
            return None
        result = amount * Decimal(str(item.hours_per_week)) * Decimal("4.33")
    elif item.frequency == "weekly":
        result = amount * Decimal("4.33")
    elif item.frequency == "biweekly":
        result = amount * Decimal("2.17")
    elif item.frequency == "semimonthly":
        result = amount * Decimal("2")
    elif item.frequency == "monthly":
        result = amount
    elif item.frequency == "yearly":
        result = amount / Decimal("12")
    else:
        return None  # unreachable given Literal, but guard anyway

    return int(result.to_integral_value(rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------

def apply_patch(household: Household, patch: dict) -> Household:
    """Return a new validated Household with patch applied; never mutates input.

    Deep-merge semantics:
    - Scalar fields: overwrite (explicit None in patch sets field to None).
    - expenses: field-wise merge.
    - members / income: merge by id.
        - Matching id → update that item field-wise.
        - Unknown id → append.
        - {"id": "x", "_delete": true} → remove that item.
    """
    # Start from a dict copy of the existing household
    base = household.model_dump()

    for key, value in patch.items():
        if key == "expenses" and isinstance(value, dict):
            # Field-wise merge into expenses
            for exp_key, exp_val in value.items():
                base["expenses"][exp_key] = exp_val
        elif key == "members" and isinstance(value, list):
            base["members"] = _merge_list(base["members"], value)
        elif key == "income" and isinstance(value, list):
            base["income"] = _merge_list(base["income"], value)
        else:
            base[key] = value

    return Household.model_validate(base)


def _merge_list(existing: list[dict], patch_items: list[dict]) -> list[dict]:
    """Merge patch_items into existing list by 'id' field."""
    # Build ordered dict by id for O(1) lookup
    by_id: dict[str, dict] = {item["id"]: dict(item) for item in existing}
    # Preserve insertion order via a list of ids
    order = [item["id"] for item in existing]

    for patch_item in patch_items:
        pid = patch_item["id"]
        if patch_item.get("_delete"):
            by_id.pop(pid, None)
            if pid in order:
                order.remove(pid)
        elif pid in by_id:
            # Field-wise update
            by_id[pid].update({k: v for k, v in patch_item.items() if k != "_delete"})
        else:
            # Append new item
            new_item = {k: v for k, v in patch_item.items() if k != "_delete"}
            by_id[pid] = new_item
            order.append(pid)

    return [by_id[pid] for pid in order if pid in by_id]


# ---------------------------------------------------------------------------
# missing_summary
# ---------------------------------------------------------------------------

# Document order for Member fields (excluding id which is required)
_MEMBER_FIELDS = [
    "age",
    "relationship",
    "is_pregnant",
    "is_disabled",
    "immigration_status",
    "is_student",
]

# Document order for IncomeItem fields
# member_id always excluded; hours_per_week conditionally excluded
_INCOME_FIELDS = [
    "kind",
    "amount_cents",
    "frequency",
    "hours_per_week",
]

# Document order for Expenses fields
# utilities_included and pays_heating_cooling conditionally excluded
_EXPENSE_FIELDS = [
    "rent_or_mortgage_cents",
    "utilities_included",
    "pays_heating_cooling",
    "dependent_care_cents",
    "child_support_paid_cents",
    "medical_expenses_elderly_disabled_cents",
]

# Top-level Household scalars (in document order after members/income/expenses)
_HOUSEHOLD_SCALARS = [
    "county",
    "purchases_and_prepares_together",
]


def missing_summary(household: Household) -> list[str]:
    """Return dotted paths of all None fields in document order.

    Path formats:
    - members[<id>].<field>
    - income[<index>].<field>   (index, not id)
    - expenses.<field>
    - <field>                   (top-level scalars)

    Exclusions:
    - income[].member_id — always excluded
    - income[].hours_per_week — excluded unless frequency == "hourly"
    - expenses.utilities_included — excluded unless rent_or_mortgage_cents is set
    - expenses.pays_heating_cooling — excluded unless rent_or_mortgage_cents is set
    """
    paths: list[str] = []

    # Members
    for member in household.members:
        for field in _MEMBER_FIELDS:
            if getattr(member, field) is None:
                paths.append(f"members[{member.id}].{field}")

    # Income (by index)
    for idx, item in enumerate(household.income):
        for field in _INCOME_FIELDS:
            if field == "hours_per_week" and item.frequency != "hourly":
                continue
            if getattr(item, field) is None:
                paths.append(f"income[{idx}].{field}")

    # Expenses
    rent_set = household.expenses.rent_or_mortgage_cents is not None
    for field in _EXPENSE_FIELDS:
        if field in ("utilities_included", "pays_heating_cooling") and not rent_set:
            continue
        if getattr(household.expenses, field) is None:
            paths.append(f"expenses.{field}")

    # Top-level scalars
    for field in _HOUSEHOLD_SCALARS:
        if getattr(household, field) is None:
            paths.append(field)

    return paths
