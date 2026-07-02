"""Generate docs/rules.md from the citations registry and table metadata.

Run from the repo root:

    uv run python scripts/gen_rules_doc.py

The output is fully generated — edit this script (or rules/citations.py),
never docs/rules.md directly.
"""

from __future__ import annotations

from pathlib import Path

from rules.citations import all_citations
from rules.tables.loader import load_table

# Which table file feeds each rule's numbers. Rules absent here are pure
# logic (no annual figure behind them).
RULE_TABLES: dict[str, str] = {
    "fns.gross_income": "rules/tables/fns.yaml",
    "fns.net_income": "rules/tables/fns.yaml",
    "fns.bbce": "rules/tables/fns.yaml",
    "fns.allotment": "rules/tables/fns.yaml",
    "fns.deductions.standard": "rules/tables/fns.yaml",
    "fns.deductions.earned_income": "rules/tables/fns.yaml",
    "fns.deductions.shelter": "rules/tables/fns.yaml",
    "fns.deductions.medical": "rules/tables/fns.yaml",
    "medicaid.expansion_adult": "rules/tables/medicaid.yaml + fpl.yaml",
    "medicaid.pregnant": "rules/tables/medicaid.yaml + fpl.yaml",
    "medicaid.child": "rules/tables/medicaid.yaml + fpl.yaml",
    "medicaid.parent_caretaker": "rules/tables/medicaid.yaml + fpl.yaml",
    "medicaid.magi_income": "rules/tables/medicaid.yaml",
    "wic.income": "rules/tables/wic.yaml + fpl.yaml",
    "lifeline.income": "rules/tables/lifeline.yaml + fpl.yaml",
    "lifeline.qualifying_program": "rules/tables/lifeline.yaml",
}

HEADER = """\
# Rules reference

<!-- GENERATED FILE — do not edit. Regenerate with:
     uv run python scripts/gen_rules_doc.py -->

Every eligibility reason the engine produces carries one of the rule ids
below, and every rule id maps to a specific section of the governing policy
manual. The engine never invents a rule: if it isn't in this table, the
screener doesn't apply it.

| Rule id | What it checks | Manual section | Fed by table |
|---|---|---|---|
"""

UPDATING = """
## Updating the annual numbers

The federal government adjusts these figures every year: FPL guidelines in
January, SNAP cost-of-living adjustments effective October 1. The engine's
numbers live in five YAML files — **updating them is a data pull request,
not a code change.**

1. Get the new source documents:
   - FPL: the HHS poverty guidelines page (linked from `rules/tables/fpl.yaml`).
   - FNS/SNAP: the USDA "SNAP Cost-of-Living Adjustments" memo for the new
     fiscal year (linked from `rules/tables/fns.yaml`).
   - Medicaid: NC DHHS MAGI percentage limits (linked from
     `rules/tables/medicaid.yaml`) — these change rarely.
   - WIC and Lifeline (`rules/tables/wic.yaml`, `rules/tables/lifeline.yaml`)
     store statutory percent-of-FPL multipliers and the Lifeline support
     amount; their dollar limits move automatically with `fpl.yaml`. Bump
     their `effective_from`/`effective_to` each cycle (WIC's IEG year runs
     July 1 → June 30) and confirm the regulations haven't changed.
2. Edit the YAML file(s): update every figure under `values:` (all money is
   **integer cents**), update `source_url`/`source_name`, and set the new
   `effective_from` / `effective_to` dates. The loader refuses to serve a
   table whose `effective_to` is in the past (`StaleTableError`), so a missed
   update fails loudly instead of screening with stale numbers.
3. Recompute the golden fixtures in `tests/fixtures/golden/*.yaml` by hand
   for the new figures, and set `verified: false` on any you changed until a
   second person re-checks them.
4. Run the suite: `uv run pytest`. The golden tests will disagree with your
   YAML edits until both are consistent — that disagreement is the safety
   check working.
5. Regenerate this file: `uv run python scripts/gen_rules_doc.py`.
6. Open a PR titled `data: FY20XX tables` containing only YAML, fixture, and
   docs changes. A reviewer verifies every figure against the source PDF
   before merge.
"""


def generate() -> str:
    citations = sorted(all_citations(), key=lambda c: c.rule_id)
    mapped = set(RULE_TABLES)
    known = {c.rule_id for c in citations}
    unknown = mapped - known
    if unknown:
        raise SystemExit(f"RULE_TABLES names unregistered rule ids: {sorted(unknown)}")

    rows = []
    for c in citations:
        table = RULE_TABLES.get(c.rule_id, "—")
        section = f"[{c.manual} {c.section}]({c.url})"
        rows.append(f"| `{c.rule_id}` | {c.title} | {section} | {table} |")

    effective = []
    for name in ("fpl", "fns", "medicaid", "wic", "lifeline"):
        t = load_table(name)
        effective.append(
            f"- `rules/tables/{name}.yaml` — {t.source_name} "
            f"(effective {t.effective_from} → {t.effective_to})"
        )

    return (
        HEADER
        + "\n".join(rows)
        + "\n\n## Current table versions\n\n"
        + "\n".join(effective)
        + "\n"
        + UPDATING
    )


if __name__ == "__main__":
    out = Path(__file__).parent.parent / "docs" / "rules.md"
    out.write_text(generate())
    print(f"wrote {out}")
