"""Versioned program-data tables for the NC Benefits Navigator rules engine.

Every numeric limit used by a program module lives in a YAML file in this
package, not in code. The annual update is therefore a data-only PR. Each
YAML file carries its authoritative source URL and effective-date range so a
human can hand-verify every figure.
"""

from rules.tables.loader import (
    StaleTableError,
    Table,
    assert_current,
    load_table,
)

__all__ = ["StaleTableError", "Table", "assert_current", "load_table"]
