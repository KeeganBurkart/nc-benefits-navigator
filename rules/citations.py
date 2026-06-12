"""Citation registry: maps rule_ids to the NC DHHS / federal policy section
each eligibility Reason is derived from.

This is the single source of truth for the Navigator's trust story — every
Reason a program module emits links back to the manual section it came from,
so a caseworker can verify the determination against current policy.

Program modules (FNS/SNAP, NC Medicaid) call ``cite(rule_id)`` for every
Reason. The docs generator (Task 14) calls ``all_citations()``.

This module is pure data + lookup. It must never import from interview/,
server/, or the anthropic package.

URL provenance (verified live at authoring time, 2026-06-12):
- NC FNS (food stamps) sections live at policies.ncdhhs.gov as
  ``/document/fns-NNN-<slug>/`` landing pages. These landing pages are the
  stable, citeable entry point (the underlying PDFs carry churny version
  suffixes like ``-1`` and are sometimes scanned images).
- NC Family & Children's Medicaid sections live at the same host as
  ``/document/ma-NNNN-<slug>/`` landing pages.
All URLs below returned HTTP 200 when fetched with a browser User-Agent
during implementation. Every entry points at a real NC DHHS manual section —
there are no federal fallbacks in this registry.
"""

from __future__ import annotations

from dataclasses import dataclass

_FNS_MANUAL = "NC FNS Manual"
_MEDICAID_MANUAL = "NC Medicaid Family & Children's Medicaid Manual"


@dataclass(frozen=True)
class Citation:
    rule_id: str
    manual: str
    section: str
    title: str
    url: str


# Registry: a literal dict, one entry per rule_id. The set of keys here is the
# binding contract for Task 4 — exactly these rule_ids, no more, no fewer.
_REGISTRY: dict[str, Citation] = {
    # ---- FNS / SNAP -----------------------------------------------------
    "fns.gross_income": Citation(
        rule_id="fns.gross_income",
        manual=_FNS_MANUAL,
        section="FNS 305",
        title="Rules for Budgeting Income (gross income test)",
        url="https://policies.ncdhhs.gov/document/fns-305-rules-for-budgeting-income/",
    ),
    "fns.net_income": Citation(
        rule_id="fns.net_income",
        manual=_FNS_MANUAL,
        section="FNS 305",
        title="Rules for Budgeting Income (net income test)",
        url="https://policies.ncdhhs.gov/document/fns-305-rules-for-budgeting-income/",
    ),
    "fns.bbce": Citation(
        rule_id="fns.bbce",
        manual=_FNS_MANUAL,
        section="FNS 220",
        title="Categorical Eligibility (broad-based categorical eligibility, 200% gross income limit)",
        url="https://policies.ncdhhs.gov/document/fns-220-categorical-eligibility/",
    ),
    "fns.elderly_disabled_exemption": Citation(
        rule_id="fns.elderly_disabled_exemption",
        manual=_FNS_MANUAL,
        section="FNS 305",
        title="Rules for Budgeting Income (elderly/disabled households exempt from the gross income test)",
        url="https://policies.ncdhhs.gov/document/fns-305-rules-for-budgeting-income/",
    ),
    "fns.allotment": Citation(
        rule_id="fns.allotment",
        manual=_FNS_MANUAL,
        section="FNS 360",
        title="Determining Benefit Levels (allotment / Thrifty Food Plan)",
        url="https://policies.ncdhhs.gov/document/fns-360-determining-benefit-levels/",
    ),
    "fns.deductions.standard": Citation(
        rule_id="fns.deductions.standard",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (standard deduction)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
    "fns.deductions.earned_income": Citation(
        rule_id="fns.deductions.earned_income",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (earned income deduction)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
    "fns.deductions.shelter": Citation(
        rule_id="fns.deductions.shelter",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (excess shelter deduction)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
    "fns.deductions.medical": Citation(
        rule_id="fns.deductions.medical",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (medical deduction for elderly/disabled members)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
    "fns.deductions.dependent_care": Citation(
        rule_id="fns.deductions.dependent_care",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (dependent care deduction)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
    "fns.deductions.child_support": Citation(
        rule_id="fns.deductions.child_support",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (legally obligated child support deduction)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
    "fns.immigration": Citation(
        rule_id="fns.immigration",
        manual=_FNS_MANUAL,
        section="FNS 227",
        title="Non-Citizen Requirements",
        url="https://policies.ncdhhs.gov/document/fns-227-non-citizen-requirements/",
    ),
    "fns.household_composition": Citation(
        rule_id="fns.household_composition",
        manual=_FNS_MANUAL,
        section="FNS 210",
        title="Household Composition",
        url="https://policies.ncdhhs.gov/document/fns-210-household-composition/",
    ),
    # ---- NC Medicaid (MAGI / Family & Children's) -----------------------
    "medicaid.expansion_adult": Citation(
        rule_id="medicaid.expansion_adult",
        manual=_MEDICAID_MANUAL,
        section="MA-3236",
        title="MAGI Adult (Medicaid Expansion)",
        url="https://policies.ncdhhs.gov/document/ma-3236-magi-adult-medicaid-expansion/",
    ),
    "medicaid.pregnant": Citation(
        rule_id="medicaid.pregnant",
        manual=_MEDICAID_MANUAL,
        section="MA-3240",
        title="Pregnant Woman Coverage",
        url="https://policies.ncdhhs.gov/document/ma-3240-pregnant-woman-coverage/",
    ),
    "medicaid.child": Citation(
        rule_id="medicaid.child",
        manual=_MEDICAID_MANUAL,
        section="MA-3415",
        title="Classification and Evaluation (Medicaid for Infants and Children coverage groups)",
        url="https://policies.ncdhhs.gov/document/ma-3415-classification-and-evaluation/",
    ),
    "medicaid.parent_caretaker": Citation(
        rule_id="medicaid.parent_caretaker",
        manual=_MEDICAID_MANUAL,
        section="MA-3235",
        title="Caretaker Relatives / Kinship",
        url="https://policies.ncdhhs.gov/document/ma-3235-caretaker-relatives-kinship/",
    ),
    "medicaid.magi_income": Citation(
        rule_id="medicaid.magi_income",
        manual=_MEDICAID_MANUAL,
        section="MA-3306",
        title="Modified Adjusted Gross Income (MAGI) methodology",
        url="https://policies.ncdhhs.gov/document/ma-3306-modified-adjusted-gross-income-magi/",
    ),
    "medicaid.immigration": Citation(
        rule_id="medicaid.immigration",
        manual=_MEDICAID_MANUAL,
        section="MA-3330",
        title="Alien Requirements (qualified non-citizen eligibility)",
        url="https://policies.ncdhhs.gov/document/ma-3330-alien-requirements/",
    ),
    # ---- Document / verification requirements ---------------------------
    "doc.identity": Citation(
        rule_id="doc.identity",
        manual=_FNS_MANUAL,
        section="FNS 205",
        title="Identity (verification of applicant identity)",
        url="https://policies.ncdhhs.gov/document/fns-205-identity/",
    ),
    "doc.income": Citation(
        rule_id="doc.income",
        manual=_FNS_MANUAL,
        section="FNS 350",
        title="Whose Income Is Counted (income verification)",
        url="https://policies.ncdhhs.gov/document/fns-350-whose-income-is-counted/",
    ),
    "doc.residency": Citation(
        rule_id="doc.residency",
        manual=_FNS_MANUAL,
        section="FNS 215",
        title="Residence (verification of NC residency)",
        url="https://policies.ncdhhs.gov/document/fns-215-residence/",
    ),
    "doc.immigration": Citation(
        rule_id="doc.immigration",
        manual=_FNS_MANUAL,
        section="FNS 227",
        title="Non-Citizen Requirements (verification of immigration status)",
        url="https://policies.ncdhhs.gov/document/fns-227-non-citizen-requirements/",
    ),
    "doc.expenses": Citation(
        rule_id="doc.expenses",
        manual=_FNS_MANUAL,
        section="FNS 340",
        title="Deductions (verification of deductible expenses)",
        url="https://policies.ncdhhs.gov/document/fns-340-deductions/",
    ),
}


def cite(rule_id: str) -> Citation:
    """Return the Citation registered for ``rule_id``.

    Raises:
        KeyError: if ``rule_id`` is not registered. The error names the
            unknown rule_id so a misspelled call is easy to spot.
    """
    try:
        return _REGISTRY[rule_id]
    except KeyError:
        raise KeyError(f"no citation registered for rule_id {rule_id!r}") from None


def all_citations() -> list[Citation]:
    """Return every registered Citation (for the docs generator)."""
    return list(_REGISTRY.values())
