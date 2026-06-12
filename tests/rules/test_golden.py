"""Golden-fixture tests: every YAML in tests/fixtures/golden/ is a hand-checked
scenario with expected per-program statuses (and FNS benefit when eligible).

Each fixture's arithmetic is shown as YAML comments in the file itself. This
test only asserts the engine reproduces the recorded expectations; it fails
loudly if a fixture is malformed or if the required coverage list shrinks.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rules.engine import screen_all
from rules.models import Household

_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "golden"

# Coverage kinds this suite must always exercise. The `name:` of at least one
# fixture must contain each substring. If a scenario kind is dropped, the
# coverage test below fails loudly.
_REQUIRED_COVERAGE = [
    "eligible-both",          # clearly eligible both
    "ineligible-both",        # clearly ineligible both
    "fns-only",               # FNS-only eligible
    "medicaid-only",          # Medicaid-only eligible
    "elderly",                # elderly with medical deductions
    "disabled",               # disabled member shelter-uncapped path
    "mixed-immigration",      # mixed immigration status
    "pregnant",               # pregnant member
    "abd",                    # 65+ ABD hand-off
    "empty",                  # empty household
    "partial",                # partial-data needs_more_info
    "minimum-allotment",      # minimum-allotment case
    "hourly",                 # hourly-wage worker
    "large",                  # large household (7+)
    "ssi",                    # SSI recipient divergence
]


def _fixture_paths() -> list[Path]:
    return sorted(p for p in _GOLDEN_DIR.glob("*.yaml"))


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise AssertionError(f"{path.name}: top-level YAML must be a mapping")
    for key in ("name", "description", "verified", "household", "expected"):
        if key not in data:
            raise AssertionError(f"{path.name}: missing required key {key!r}")
    if not isinstance(data["household"], dict):
        raise AssertionError(f"{path.name}: 'household' must be a mapping")
    expected = data["expected"]
    if not isinstance(expected, dict) or "fns" not in expected or "medicaid" not in expected:
        raise AssertionError(f"{path.name}: 'expected' must have 'fns' and 'medicaid' entries")
    return data


def test_at_least_fifteen_fixtures():
    paths = _fixture_paths()
    assert len(paths) >= 15, f"expected >= 15 golden fixtures, found {len(paths)}"


def test_required_coverage_present():
    names = [_load(p)["name"] for p in _fixture_paths()]
    blob = "\n".join(names)
    for kind in _REQUIRED_COVERAGE:
        assert kind in blob, f"no golden fixture covers scenario kind {kind!r}"


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name)
def test_golden_fixture(path: Path):
    data = _load(path)
    household = Household.model_validate(data["household"])
    result = screen_all(household)

    by_program = {p.program: p for p in result.programs}
    expected = data["expected"]

    for program in ("fns", "medicaid"):
        exp = expected[program]
        got = by_program[program]
        assert got.status == exp["status"], (
            f"{path.name}: {program} status {got.status!r} != expected {exp['status']!r}"
        )
        if "estimated_benefit_cents" in exp:
            assert got.estimated_benefit_cents == exp["estimated_benefit_cents"], (
                f"{path.name}: {program} benefit {got.estimated_benefit_cents} "
                f"!= expected {exp['estimated_benefit_cents']}"
            )
        else:
            # No benefit asserted -> the program must not have produced one
            # (Medicaid is always None; FNS is None unless likely_eligible).
            assert got.estimated_benefit_cents is None, (
                f"{path.name}: {program} expected no benefit but got "
                f"{got.estimated_benefit_cents}"
            )
