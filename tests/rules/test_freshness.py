"""Table freshness + citation link health.

The freshness sentinel runs in the default suite: it fails loudly the day any
shipped table goes stale, so a missed annual update can never screen a family
with out-of-date numbers. The link check is network-marked (excluded by
default) so offline/CI runs stay hermetic; run it manually:

    uv run pytest -m linkcheck
"""

from __future__ import annotations

from datetime import date

import pytest

from rules.citations import all_citations
from rules.tables.loader import assert_current, load_table

_TABLE_NAMES = ("fpl", "fns", "medicaid", "wic", "lifeline")


@pytest.mark.parametrize("name", _TABLE_NAMES)
def test_table_is_current_today(name: str):
    """effective_from <= today <= effective_to for every shipped table."""
    table = load_table(name)
    today = date.today()
    # Explicit bounds check first for a clear message, then the engine's guard.
    assert table.effective_from <= today <= table.effective_to, (
        f"table '{name}' is stale for {today.isoformat()}: effective "
        f"{table.effective_from.isoformat()}..{table.effective_to.isoformat()} "
        f"— pull the new figures (see docs/rules.md)"
    )
    assert_current(table, today)  # must not raise StaleTableError


# ---------------------------------------------------------------------------
# Network link check (opt-in)
# ---------------------------------------------------------------------------


def _citation_urls() -> list[str]:
    return sorted({c.url for c in all_citations()})


def _table_source_urls() -> list[str]:
    return sorted({load_table(n).source_url for n in _TABLE_NAMES})


@pytest.mark.linkcheck
@pytest.mark.parametrize("url", _citation_urls() + _table_source_urls())
def test_source_url_returns_200(url: str):
    import httpx

    # A browser-like UA: some .gov hosts 403 the default httpx agent.
    headers = {"User-Agent": "Mozilla/5.0 (compatible; nc-benefits-navigator-linkcheck)"}
    with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
        resp = client.get(url)
    assert resp.status_code == 200, f"{url} -> HTTP {resp.status_code}"
