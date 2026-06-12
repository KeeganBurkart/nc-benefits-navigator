"""Anthropic tool schemas and dispatch for the fact-extraction interview loop.

The LLM never decides eligibility. It interviews a caseworker, extracts facts
into structured patches via the ``update_household`` tool, and relays whatever
the deterministic engine returned via ``get_screening_status``.

This module imports from ``rules/`` only — never the reverse.

Money convention: the model speaks DOLLARS. It sends dollar-named fields
(``amount``, ``rent_or_mortgage``, ``dependent_care``, ``child_support_paid``,
``medical_expenses_elderly_disabled``) and this dispatcher converts them to the
``*_cents`` integer fields the rules models expect. The model must never write
``_cents`` field names directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import ValidationError

from rules.engine import ScreeningResult, screen_all
from rules.models import Household, apply_patch

# ---------------------------------------------------------------------------
# Session state (the server in Task 9 owns/wraps this; defined minimally here)
# ---------------------------------------------------------------------------


@dataclass
class SessionState:
    """Minimal mutable interview session state.

    The server (Task 9) builds and owns the real session; the interview layer
    only needs these three attributes. ``messages`` is in Anthropic message
    format (list of ``{"role": ..., "content": ...}`` dicts).
    """

    household: Household = field(default_factory=Household)
    screening: ScreeningResult | None = None
    messages: list[dict] = field(default_factory=list)


class SessionStateLike(Protocol):
    household: Household
    screening: ScreeningResult | None
    messages: list[dict]


# ---------------------------------------------------------------------------
# Dollar→cents field mapping
# ---------------------------------------------------------------------------

# income[].amount (dollars) → amount_cents
_INCOME_MONEY = {"amount": "amount_cents"}

# expenses dollar-named fields → *_cents fields
_EXPENSE_MONEY = {
    "rent_or_mortgage": "rent_or_mortgage_cents",
    "dependent_care": "dependent_care_cents",
    "child_support_paid": "child_support_paid_cents",
    "medical_expenses_elderly_disabled": "medical_expenses_elderly_disabled_cents",
}


def _dollars_to_cents(value: object) -> object:
    """Convert a dollar amount (int/float) to integer cents, half-up.

    Non-numeric values are returned untouched so pydantic raises the natural
    validation error downstream.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    # Round to the nearest cent; avoid float drift (1250.50 → 125050, not 125049).
    return int(round(value * 100))


def _convert_patch_money(patch: dict) -> dict:
    """Return a copy of ``patch`` with dollar-named money fields mapped to
    their ``*_cents`` model fields and converted to integer cents.

    Leaves all other keys untouched. Operates on income items (list, by id)
    and the expenses object.
    """
    converted: dict = dict(patch)

    if isinstance(patch.get("income"), list):
        new_income = []
        for item in patch["income"]:
            if isinstance(item, dict):
                new_item = dict(item)
                for dollar_key, cents_key in _INCOME_MONEY.items():
                    if dollar_key in new_item:
                        new_item[cents_key] = _dollars_to_cents(new_item.pop(dollar_key))
                new_income.append(new_item)
            else:
                new_income.append(item)
        converted["income"] = new_income

    if isinstance(patch.get("expenses"), dict):
        new_expenses = dict(patch["expenses"])
        for dollar_key, cents_key in _EXPENSE_MONEY.items():
            if dollar_key in new_expenses:
                new_expenses[cents_key] = _dollars_to_cents(new_expenses.pop(dollar_key))
        converted["expenses"] = new_expenses

    return converted


# ---------------------------------------------------------------------------
# Compact screening summary (reused by Task 9's PATCH endpoint)
# ---------------------------------------------------------------------------


def compact_screening(screening: ScreeningResult) -> dict:
    """Build the compact per-program screening summary the model/UI consume.

    Shape::

        {
          "programs": [
            {"program": "fns", "label": "...", "status": "...",
             "reason": "<one-line headline or ''>",
             "estimated_benefit_cents": <int|null>},
            ...
          ],
          "missing_fields": [...],
        }
    """
    programs = []
    for result in screening.programs:
        headline = result.reasons[0].text if result.reasons else ""
        programs.append(
            {
                "program": result.program,
                "label": result.program_label,
                "status": result.status,
                "reason": headline,
                "estimated_benefit_cents": result.estimated_benefit_cents,
            }
        )
    return {
        "programs": programs,
        "missing_fields": list(screening.missing_fields),
    }


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_UPDATE_HOUSEHOLD_DESCRIPTION = (
    "Record facts about the household into the screening engine. Send ONLY the "
    "fields that changed as a partial `patch` object.\n\n"
    "PATCH SEMANTICS:\n"
    "- Scalar fields overwrite the current value.\n"
    "- `members` and `income` are lists merged BY `id`: include an item's `id` "
    "to update it, a new `id` to add it, and `{\"id\": \"m1\", \"_delete\": true}` "
    "to remove it.\n"
    "- `expenses` is an object merged field-by-field.\n"
    "- Unknown / misspelled field names are REJECTED — only use the names listed below.\n\n"
    "MONEY IS IN DOLLARS: every money amount is a dollar figure (floats are fine, "
    "e.g. 1250.50 means $1,250.50). The system converts dollars to cents for you. "
    "NEVER write field names ending in `_cents`.\n\n"
    "members[] — each needs an `id` (a short string you choose, e.g. \"m1\"); fields:\n"
    "  age (int 0-125), relationship (one of: self, spouse, child, other_relative, "
    "unrelated), is_pregnant (bool), is_disabled (bool), immigration_status (one of: "
    "citizen, qualified_immigrant, not_qualified, unknown), is_student (bool).\n\n"
    "income[] — each needs an `id`; fields:\n"
    "  member_id (id of the member who earns it), kind (one of: wages, self_employment, "
    "unemployment, ssi, ssdi, social_security, child_support_received, other), "
    "amount (DOLLARS), frequency (one of: hourly, weekly, biweekly, semimonthly, "
    "monthly, yearly), hours_per_week (number, only when frequency is hourly).\n\n"
    "expenses — object; monthly amounts; fields:\n"
    "  rent_or_mortgage (DOLLARS), utilities_included (bool), pays_heating_cooling (bool), "
    "dependent_care (DOLLARS), child_support_paid (DOLLARS), "
    "medical_expenses_elderly_disabled (DOLLARS).\n\n"
    "top-level — county (string), purchases_and_prepares_together (bool)."
)

_GET_SCREENING_DESCRIPTION = (
    "Get the current screening status from the deterministic engine: each "
    "program's status, the headline reason, the estimated benefit, and the list "
    "of facts still missing. Call this to know what to ask next or to relay "
    "results to the caseworker. It takes no input."
)

TOOLS: list[dict] = [
    {
        "name": "update_household",
        "description": _UPDATE_HOUSEHOLD_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": (
                        "Partial household patch — only the fields that changed. "
                        "Money fields are in DOLLARS."
                    ),
                }
            },
            "required": ["patch"],
        },
    },
    {
        "name": "get_screening_status",
        "description": _GET_SCREENING_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _ensure_screening(state: SessionStateLike) -> ScreeningResult:
    if state.screening is None:
        state.screening = screen_all(state.household)
    return state.screening


def dispatch(state: SessionStateLike, tool_name: str, tool_input: dict) -> str:
    """Execute a tool call against ``state`` and return a JSON string.

    Never raises for ordinary failures — validation errors and unknown tools
    are returned as ``{"error": ...}`` JSON. On a successful update, ``state``
    is mutated (household + screening stored).
    """
    if tool_name == "update_household":
        patch = tool_input.get("patch", {})
        if not isinstance(patch, dict):
            return json.dumps({"error": "patch: must be an object"})
        converted = _convert_patch_money(patch)
        try:
            new_household = apply_patch(state.household, converted)
        except ValidationError as exc:
            return json.dumps({"error": _format_validation_error(exc)})
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        screening = screen_all(new_household)
        state.household = new_household
        state.screening = screening
        return json.dumps(
            {
                "household": new_household.model_dump(),
                "screening": compact_screening(screening),
            }
        )

    if tool_name == "get_screening_status":
        screening = _ensure_screening(state)
        return json.dumps(compact_screening(screening))

    return json.dumps({"error": f"unknown tool: {tool_name}"})


def _format_validation_error(exc: ValidationError) -> str:
    """Render the first pydantic error as ``<field path>: <message>``."""
    errors = exc.errors()
    if not errors:
        return str(exc)
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
    return f"{loc}: {first.get('msg', 'invalid')}"
