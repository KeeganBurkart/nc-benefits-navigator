"""Small helpers shared by program eligibility modules.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package. It holds only formatting/dedup helpers
that would otherwise be duplicated verbatim across program modules.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rules.citations import cite
from rules.programs.types import CitationOut, Reason
from rules.tables.loader import load_table

# Human-readable income document name per income kind (rule doc.income).
# Used by both fns.py and medicaid.py document builders.
INCOME_DOC_NAMES = {
    "wages": "Pay stubs (last 30 days)",
    "self_employment": "Self-employment records",
    "unemployment": "Unemployment award letter",
    "ssi": "SSI award letter",
    "ssdi": "SSDI award letter",
    "social_security": "Social Security award letter",
    "child_support_received": "Child support records",
    "other": "Documentation of other income",
}


def fmt(cents: int) -> str:
    """Format integer cents as a $X,XXX.XX dollar string (e.g. 264670 -> $2,646.70)."""
    dollars = Decimal(cents) / Decimal(100)
    return f"${dollars:,.2f}"


def reason(rule_id: str, text: str) -> Reason:
    return Reason(rule_id=rule_id, text=text, citation=CitationOut.from_citation(cite(rule_id)))


def fpl_monthly(size: int) -> int:
    """100% FPL monthly cents for a household of ``size`` (>= 1).

    Sizes 1..8 come straight from the published chart; beyond 8 we add
    ``additional_member_cents`` per extra member (HHS's method). ``load_table``
    is lru_cached, so this is a memory lookup after the first call.
    """
    fpl = load_table("fpl").values
    by_size = fpl["monthly_cents_by_household_size"]
    if size <= 8:
        return int(by_size[size])
    return int(by_size[8]) + int(fpl["additional_member_cents"]) * (size - 8)


def pct_of_fpl(pct: int, size: int) -> int:
    """``pct``% of the monthly FPL for ``size``, rounded half-up to the cent."""
    return int(
        (Decimal(fpl_monthly(size)) * Decimal(pct) / Decimal(100))
        .to_integral_value(rounding=ROUND_HALF_UP)
    )


def dedup(paths: list[str]) -> list[str]:
    """Preserve order, drop duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
