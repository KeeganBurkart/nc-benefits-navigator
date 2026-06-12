"""Tests for rules/citations.py — written before implementation (TDD).

These tests must NOT hit the network. URL liveness is verified at
implementation time, not here.
"""
import dataclasses

import pytest

# The exact, complete set of rule_ids the registry must contain — no more,
# no fewer. Mirrors the Task 4 contract.
RULE_IDS = [
    "fns.gross_income",
    "fns.net_income",
    "fns.bbce",
    "fns.elderly_disabled_exemption",
    "fns.allotment",
    "fns.deductions.standard",
    "fns.deductions.earned_income",
    "fns.deductions.shelter",
    "fns.deductions.medical",
    "fns.deductions.dependent_care",
    "fns.deductions.child_support",
    "fns.immigration",
    "fns.household_composition",
    "medicaid.expansion_adult",
    "medicaid.pregnant",
    "medicaid.child",
    "medicaid.parent_caretaker",
    "medicaid.magi_income",
    "medicaid.immigration",
    "doc.identity",
    "doc.income",
    "doc.residency",
    "doc.immigration",
    "doc.expenses",
]


# ===========================================================================
# Citation dataclass shape
# ===========================================================================

def test_citation_is_frozen_dataclass():
    from rules.citations import Citation

    assert dataclasses.is_dataclass(Citation)
    c = Citation(
        rule_id="x",
        manual="m",
        section="s",
        title="t",
        url="https://example.com",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.rule_id = "y"  # type: ignore[misc]


def test_citation_has_expected_fields():
    from rules.citations import Citation

    field_names = {f.name for f in dataclasses.fields(Citation)}
    assert field_names == {"rule_id", "manual", "section", "title", "url"}


# ===========================================================================
# cite()
# ===========================================================================

@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_cite_returns_well_formed_citation(rule_id):
    from rules.citations import Citation, cite

    c = cite(rule_id)
    assert isinstance(c, Citation)
    assert c.rule_id == rule_id
    assert c.manual.strip(), f"{rule_id}: manual is empty"
    assert c.section.strip(), f"{rule_id}: section is empty"
    assert c.title.strip(), f"{rule_id}: title is empty"
    assert c.url.startswith("https://"), f"{rule_id}: url not https: {c.url!r}"


def test_cite_unknown_raises_keyerror_mentioning_id():
    from rules.citations import cite

    with pytest.raises(KeyError) as excinfo:
        cite("fns.does_not_exist")
    assert "fns.does_not_exist" in str(excinfo.value)


# ===========================================================================
# Registry integrity
# ===========================================================================

def test_all_citations_returns_every_entry():
    from rules.citations import all_citations

    cites = all_citations()
    assert isinstance(cites, list)
    assert {c.rule_id for c in cites} == set(RULE_IDS)


def test_registry_has_no_duplicate_rule_ids():
    from rules.citations import all_citations

    cites = all_citations()
    rule_ids = [c.rule_id for c in cites]
    assert len(rule_ids) == len(RULE_IDS)
    assert len(set(rule_ids)) == len(rule_ids)


def test_registry_is_exactly_the_contract_set():
    """No extra and no missing rule_ids vs. the binding contract list."""
    from rules.citations import all_citations

    registered = {c.rule_id for c in all_citations()}
    assert registered == set(RULE_IDS)


def test_cite_matches_all_citations():
    from rules.citations import all_citations, cite

    for c in all_citations():
        assert cite(c.rule_id) == c
