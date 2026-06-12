"""Loader for versioned program-data tables.

Pure deterministic logic: this module reads YAML data files shipped alongside
it and exposes them as frozen ``Table`` objects. It must never import from
``interview/``, ``server/``, or the anthropic package.

A table's *name* is the stem of its YAML file (``fpl`` -> ``fpl.yaml``). Each
file is read at most once per process and cached.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

_TABLES_DIR = Path(__file__).resolve().parent

# Schema keys that live at the top level of every table file.
_REQUIRED_FIELDS = (
    "source_url",
    "source_name",
    "effective_from",
    "effective_to",
    "values",
)


class StaleTableError(Exception):
    """Raised when a table is consulted for a date outside its effective range."""


@dataclass(frozen=True)
class Table:
    """An immutable view of one versioned data file."""

    name: str
    values: dict
    source_url: str
    source_name: str
    effective_from: date
    effective_to: date


def _coerce_date(value: object, *, field: str, name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"table '{name}': field '{field}' is not a date: {value!r}")


@lru_cache(maxsize=None)
def load_table(name: str) -> Table:
    """Load and cache the table named ``name`` (the YAML filename stem).

    Raises ``FileNotFoundError`` with a clear message for an unknown name.
    """
    path = _TABLES_DIR / f"{name}.yaml"
    if not path.is_file():
        available = sorted(p.stem for p in _TABLES_DIR.glob("*.yaml"))
        raise FileNotFoundError(
            f"unknown table '{name}': no file {path.name} in {_TABLES_DIR} "
            f"(available: {', '.join(available) or 'none'})"
        )

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"table '{name}': top-level YAML must be a mapping")

    missing = [f for f in _REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ValueError(f"table '{name}': missing required field(s) {missing}")

    values = raw["values"]
    if not isinstance(values, dict):
        raise ValueError(f"table '{name}': 'values' must be a mapping")

    return Table(
        name=name,
        values=values,
        source_url=str(raw["source_url"]),
        source_name=str(raw["source_name"]),
        effective_from=_coerce_date(raw["effective_from"], field="effective_from", name=name),
        effective_to=_coerce_date(raw["effective_to"], field="effective_to", name=name),
    )


def assert_current(table: Table, today: date) -> None:
    """Raise ``StaleTableError`` if ``today`` is outside the table's range.

    The range is inclusive on both ends:
    ``effective_from <= today <= effective_to``.
    """
    if today < table.effective_from or today > table.effective_to:
        raise StaleTableError(
            f"table '{table.name}' is not current for {today.isoformat()}: "
            f"effective {table.effective_from.isoformat()} through "
            f"{table.effective_to.isoformat()} (effective_to={table.effective_to.isoformat()})"
        )
