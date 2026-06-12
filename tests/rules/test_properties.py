"""Property-based tests for the screening engine (Hypothesis).

These exercise invariants that must hold across the whole input space, not just
the hand-picked golden fixtures:

1. ``screen_all`` never raises for any valid household (including empty).
2. Adding income never flips a program likely_ineligible -> likely_eligible.
3. Increasing a deductible FNS expense never DECREASES the allotment.
4. ``screen_all`` is idempotent at the ``model_dump()`` level.
5. Output shape invariants: citation urls are https, statuses are in the
   Literal, and every missing-field path matches the dotted-path regex.

Households are generated within the model's validation bounds (age 0..125,
cents >= 0, valid literals, unique ids), covering 0..6 members, partial/missing
fields everywhere, every income kind/frequency (incl. hourly with/without
hours), expenses present/absent, all immigration statuses, and
purchases_and_prepares_together None/True/False.
"""
from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rules.engine import screen_all
from rules.models import Expenses, Household, IncomeItem, Member
from rules.programs.types import ProgramResult

_STATUSES = {"likely_eligible", "likely_ineligible", "needs_more_info"}

_MISSING_PATH_RE = re.compile(
    r"^(members\[[^\]]+\]\.\w+|income\[\d+\]\.\w+|expenses\.\w+|\w+)$"
)

_IMMIGRATION = [None, "citizen", "qualified_immigrant", "not_qualified", "unknown"]
_RELATIONSHIP = [None, "self", "spouse", "child", "other_relative", "unrelated"]
_INCOME_KINDS = [
    None,
    "wages",
    "self_employment",
    "unemployment",
    "ssi",
    "ssdi",
    "social_security",
    "child_support_received",
    "other",
]
_FREQUENCIES = [None, "hourly", "weekly", "biweekly", "semimonthly", "monthly", "yearly"]

_cents = st.integers(min_value=0, max_value=2_000_000)
_opt_bool = st.sampled_from([None, True, False])


@st.composite
def _members(draw) -> list[Member]:
    n = draw(st.integers(min_value=0, max_value=6))
    out: list[Member] = []
    for i in range(n):
        out.append(
            Member(
                id=f"m{i}",
                age=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=125))),
                relationship=draw(st.sampled_from(_RELATIONSHIP)),
                is_pregnant=draw(_opt_bool),
                is_disabled=draw(_opt_bool),
                immigration_status=draw(st.sampled_from(_IMMIGRATION)),
                is_student=draw(_opt_bool),
            )
        )
    return out


@st.composite
def _income(draw) -> list[IncomeItem]:
    n = draw(st.integers(min_value=0, max_value=4))
    out: list[IncomeItem] = []
    for i in range(n):
        freq = draw(st.sampled_from(_FREQUENCIES))
        hours = None
        if freq == "hourly":
            # cover hourly both with and without hours_per_week
            hours = draw(st.one_of(st.none(), st.floats(min_value=0, max_value=80)))
        out.append(
            IncomeItem(
                id=f"i{i}",
                member_id=draw(st.one_of(st.none(), st.sampled_from([f"m{j}" for j in range(6)]))),
                kind=draw(st.sampled_from(_INCOME_KINDS)),
                amount_cents=draw(st.one_of(st.none(), _cents)),
                frequency=freq,
                hours_per_week=hours,
            )
        )
    return out


@st.composite
def _expenses(draw) -> Expenses:
    return Expenses(
        rent_or_mortgage_cents=draw(st.one_of(st.none(), _cents)),
        utilities_included=draw(_opt_bool),
        pays_heating_cooling=draw(_opt_bool),
        dependent_care_cents=draw(st.one_of(st.none(), _cents)),
        child_support_paid_cents=draw(st.one_of(st.none(), _cents)),
        medical_expenses_elderly_disabled_cents=draw(st.one_of(st.none(), _cents)),
    )


@st.composite
def households(draw) -> Household:
    return Household(
        members=draw(_members()),
        income=draw(_income()),
        expenses=draw(_expenses()),
        county=draw(st.one_of(st.none(), st.sampled_from(["New Hanover", "Brunswick", "Pender"]))),
        purchases_and_prepares_together=draw(_opt_bool),
    )


def _by_program(result, name: str) -> ProgramResult:
    return next(p for p in result.programs if p.program == name)


# ---------------------------------------------------------------------------
# 1. Never raises
# ---------------------------------------------------------------------------

@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(households())
def test_screen_all_never_raises(hh: Household):
    result = screen_all(hh)
    assert [p.program for p in result.programs] == ["fns", "medicaid"]


def test_screen_all_empty_household():
    # Explicit empty-household coverage (not relying on the generator).
    result = screen_all(Household())
    assert [p.program for p in result.programs] == ["fns", "medicaid"]


# ---------------------------------------------------------------------------
# 2. Income monotonicity: adding income never flips ineligible -> eligible
# ---------------------------------------------------------------------------

@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(households(), st.sampled_from(["fns", "medicaid"]), _cents, st.sampled_from(_INCOME_KINDS[1:]))
def test_adding_income_never_flips_to_eligible(hh: Household, program: str, extra_cents: int, kind: str):
    before = _by_program(screen_all(hh), program)
    if before.status != "likely_ineligible":
        return  # only the ineligible -> eligible flip is forbidden

    used_ids = {item.id for item in hh.income}
    new_id = "extra"
    while new_id in used_ids:
        new_id += "x"
    bumped = Household(
        members=hh.members,
        income=[*hh.income, IncomeItem(id=new_id, kind=kind, amount_cents=extra_cents, frequency="monthly")],
        expenses=hh.expenses,
        county=hh.county,
        purchases_and_prepares_together=hh.purchases_and_prepares_together,
    )
    after = _by_program(screen_all(bumped), program)
    assert after.status != "likely_eligible"


# ---------------------------------------------------------------------------
# 3. FNS deduction monotonicity: more deductible expense never lowers allotment
# ---------------------------------------------------------------------------

@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(households(), _cents)
def test_fns_increasing_deduction_never_lowers_allotment(hh: Household, bump: int):
    fns_before = _by_program(screen_all(hh), "fns")
    if fns_before.status != "likely_eligible":
        return

    exp = hh.expenses
    base_dc = exp.dependent_care_cents or 0
    bumped_exp = exp.model_copy(update={"dependent_care_cents": base_dc + bump})
    bumped = hh.model_copy(update={"expenses": bumped_exp})

    fns_after = _by_program(screen_all(bumped), "fns")
    if fns_after.status != "likely_eligible":
        return  # only compare when both runs land likely_eligible
    assert fns_after.estimated_benefit_cents >= fns_before.estimated_benefit_cents


# ---------------------------------------------------------------------------
# 4. Idempotence
# ---------------------------------------------------------------------------

@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(households())
def test_idempotent(hh: Household):
    assert screen_all(hh).model_dump() == screen_all(hh).model_dump()


# ---------------------------------------------------------------------------
# 5. Output shape invariants
# ---------------------------------------------------------------------------

@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(households())
def test_output_shape_invariants(hh: Household):
    result = screen_all(hh)

    # Engine-level missing-fields union: every path matches the dotted-path regex.
    for path in result.missing_fields:
        assert _MISSING_PATH_RE.match(path), f"bad missing path: {path!r}"

    for program in result.programs:
        assert program.status in _STATUSES
        for path in program.missing_fields:
            assert _MISSING_PATH_RE.match(path), f"bad missing path: {path!r}"
        for r in program.reasons:
            assert r.citation.url, "citation url must be non-empty"
            assert r.citation.url.startswith("https"), f"citation url must be https: {r.citation.url!r}"
