"""Engine façade: run a household through every program and assemble the
single screening result the API/UI consume.

This module is the one public entry point for screening. It runs the programs
in the registry in a stable order (FNS then Medicaid), echoes the household
back, unions the per-program missing-field lists (deduped, first-seen order),
and attaches the fixed legal disclaimer.

The ``ScreeningResult`` shape — and its ``model_dump()`` / ``model_dump_json()``
JSON — is the binding API/UI contract.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rules.models import Household
from rules.programs import PROGRAMS
from rules.programs.types import ProgramResult

# The programs run in this exact order; the result list mirrors it.
_PROGRAM_ORDER = ("fns", "medicaid")

DISCLAIMER = (
    "This is a screening estimate, not an eligibility determination. "
    "Only your county DSS can determine eligibility. "
    "Apply online at https://epass.nc.gov."
)


class ScreeningResult(BaseModel):
    """The full screening across every supported program for one household."""

    model_config = ConfigDict(frozen=True)

    programs: list[ProgramResult]
    household: Household
    missing_fields: list[str]
    generated_disclaimer: str


def screen_all(household: Household) -> ScreeningResult:
    """Screen ``household`` against every program and assemble the result.

    The ``programs`` list is in ``_PROGRAM_ORDER`` (fns then medicaid).
    ``missing_fields`` is the union of every program's ``missing_fields``,
    deduped, in first-seen order across programs.
    """
    results: list[ProgramResult] = [PROGRAMS[name](household) for name in _PROGRAM_ORDER]

    seen: set[str] = set()
    missing_fields: list[str] = []
    for result in results:
        for path in result.missing_fields:
            if path not in seen:
                seen.add(path)
                missing_fields.append(path)

    return ScreeningResult(
        programs=results,
        household=household,
        missing_fields=missing_fields,
        generated_disclaimer=DISCLAIMER,
    )
