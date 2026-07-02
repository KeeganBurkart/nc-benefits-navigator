"""Program eligibility modules and the registry that maps program ids to them.

Each program module exposes ``evaluate(household) -> ProgramResult``. The
``PROGRAMS`` registry is the single dispatch point the API/UI use to run a
household through every supported program.
"""

from __future__ import annotations

from collections.abc import Callable

from rules.models import Household
from rules.programs import fns, lifeline, medicaid, wic
from rules.programs.types import ProgramResult

PROGRAMS: dict[str, Callable[[Household], ProgramResult]] = {
    "fns": fns.evaluate,
    "medicaid": medicaid.evaluate,
    "wic": wic.evaluate,
    "lifeline": lifeline.evaluate,
}
