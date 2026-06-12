"""Small helpers shared by program eligibility modules.

Pure deterministic logic: this module must never import from ``interview/``,
``server/``, or the anthropic package. It holds only formatting/dedup helpers
that would otherwise be duplicated verbatim across program modules.
"""

from __future__ import annotations

from decimal import Decimal

from rules.citations import cite
from rules.programs.types import CitationOut, Reason


def fmt(cents: int) -> str:
    """Format integer cents as a $X,XXX.XX dollar string (e.g. 264670 -> $2,646.70)."""
    dollars = Decimal(cents) / Decimal(100)
    return f"${dollars:,.2f}"


def reason(rule_id: str, text: str) -> Reason:
    return Reason(rule_id=rule_id, text=text, citation=CitationOut.from_citation(cite(rule_id)))


def dedup(paths: list[str]) -> list[str]:
    """Preserve order, drop duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
