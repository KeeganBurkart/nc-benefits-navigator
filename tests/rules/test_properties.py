"""Property-based tests for the screening engine (Hypothesis).

These exercise invariants that must hold across the whole input space, not just
the hand-picked golden fixtures:

1. ``screen_all`` never raises for any valid household (including empty).
2. Adding income never flips a program likely_ineligible -> likely_eligible.
3. Monotonicity: increasing a deductible FNS expense (dependent care, rent)
   never DECREASES the allotment; increasing income never INCREASES it; every
   percent-of-FPL limit strictly grows with household size.
4. ``screen_all`` is idempotent at the ``model_dump()`` level.
5. Output shape invariants: citation urls are https, statuses are in the
   Literal, and every missing-field path matches the dotted-path regex.

6. Cross-program invariants: WIC catches an over-income household adjunctively
   when Medicaid/FNS is eligible; Lifeline never income-resolves while FNS and
   Medicaid are both undecided.

Households are generated within the model's validation bounds (age 0..125,
cents >= 0, valid literals, unique ids), covering 0..10 members and income up
to $50k/month, partial/missing fields everywhere, every income kind/frequency
(incl. hourly with/without hours), expenses present/absent, all immigration
statuses, and purchases_and_prepares_together None/True/False.
"""
from __future__ import annotations

import re

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from rules.engine import screen_all
from rules.models import Expenses, Household, IncomeItem, Member
from rules.programs._shared import pct_of_fpl
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

# Bounds widened now that the size- and FPL-extrapolation paths (>8/>10
# members) are exercised: up to 10 members and $50k/month per income item.
_cents = st.integers(min_value=0, max_value=5_000_000)
_opt_bool = st.sampled_from([None, True, False])


@st.composite
def _members(draw) -> list[Member]:
    n = draw(st.integers(min_value=0, max_value=10))
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
                member_id=draw(st.one_of(st.none(), st.sampled_from([f"m{j}" for j in range(10)]))),
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


@st.composite
def ineligible_households(draw) -> Household:
    """Complete households with very high income so FNS/Medicaid likely_ineligible is common.

    Wages 700000-2000000 cents/mo, 1-4 members, all member fields filled,
    purchases_and_prepares_together=True.
    """
    n = draw(st.integers(min_value=1, max_value=4))
    members = [
        Member(
            id=f"m{i}",
            age=draw(st.integers(min_value=25, max_value=55)),
            relationship=draw(st.sampled_from(["self", "spouse", "child", "other_relative"])),
            is_pregnant=False,
            is_disabled=False,
            immigration_status=draw(st.sampled_from(["citizen", "qualified_immigrant"])),
            is_student=False,
        )
        for i in range(n)
    ]
    income = [
        IncomeItem(
            id="i0",
            member_id="m0",
            kind="wages",
            amount_cents=draw(st.integers(min_value=700_000, max_value=2_000_000)),
            frequency="monthly",
        )
    ]
    return Household(
        members=members,
        income=income,
        expenses=Expenses(
            rent_or_mortgage_cents=draw(st.integers(min_value=0, max_value=300_000)),
            pays_heating_cooling=draw(st.sampled_from([True, False])),
        ),
        county=draw(st.sampled_from(["New Hanover", "Brunswick", "Pender"])),
        purchases_and_prepares_together=True,
    )


@st.composite
def eligible_fns_households(draw) -> Household:
    """Complete low-income households so FNS likely_eligible is common.

    Wages 50000-150000 cents/mo, 1-3 members, rent present, pays_heating_cooling set.
    """
    n = draw(st.integers(min_value=1, max_value=3))
    members = [
        Member(
            id=f"m{i}",
            age=draw(st.integers(min_value=25, max_value=55)),
            relationship=draw(st.sampled_from(["self", "spouse", "child", "other_relative"])),
            is_pregnant=False,
            is_disabled=False,
            immigration_status=draw(st.sampled_from(["citizen", "qualified_immigrant"])),
            is_student=False,
        )
        for i in range(n)
    ]
    income = [
        IncomeItem(
            id="i0",
            member_id="m0",
            kind="wages",
            amount_cents=draw(st.integers(min_value=50_000, max_value=150_000)),
            frequency="monthly",
        )
    ]
    return Household(
        members=members,
        income=income,
        expenses=Expenses(
            rent_or_mortgage_cents=draw(st.integers(min_value=50_000, max_value=200_000)),
            pays_heating_cooling=draw(st.sampled_from([True, False])),
        ),
        county=draw(st.sampled_from(["New Hanover", "Brunswick", "Pender"])),
        purchases_and_prepares_together=True,
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
    assert [p.program for p in result.programs] == ["fns", "medicaid", "wic", "lifeline"]


# ---------------------------------------------------------------------------
# 2. Income monotonicity: adding income never flips ineligible -> eligible
# ---------------------------------------------------------------------------

@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
# Lifeline is excluded on purpose: adding an SSI income item legitimately flips
# it to eligible (receiving SSI is itself a qualifying program).
@given(ineligible_households(), st.sampled_from(["fns", "medicaid", "wic"]), _cents, st.sampled_from(_INCOME_KINDS[1:]))
def test_adding_income_never_flips_to_eligible(hh: Household, program: str, extra_cents: int, kind: str):
    before = _by_program(screen_all(hh), program)
    assume(before.status == "likely_ineligible")  # only the ineligible -> eligible flip is forbidden

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
@given(eligible_fns_households(), _cents)
def test_fns_increasing_deduction_never_lowers_allotment(hh: Household, bump: int):
    fns_before = _by_program(screen_all(hh), "fns")
    assume(fns_before.status == "likely_eligible")

    exp = hh.expenses
    base_dc = exp.dependent_care_cents or 0
    bumped_exp = exp.model_copy(update={"dependent_care_cents": base_dc + bump})
    bumped = hh.model_copy(update={"expenses": bumped_exp})

    fns_after = _by_program(screen_all(bumped), "fns")
    assume(fns_after.status == "likely_eligible")  # only compare when both runs land likely_eligible
    assert fns_after.estimated_benefit_cents >= fns_before.estimated_benefit_cents


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(eligible_fns_households(), st.integers(min_value=1, max_value=200_000))
def test_fns_increasing_income_never_raises_allotment(hh: Household, bump: int):
    fns_before = _by_program(screen_all(hh), "fns")
    assume(fns_before.status == "likely_eligible")

    inc = hh.income[0]
    bumped_inc = inc.model_copy(update={"amount_cents": inc.amount_cents + bump})
    bumped = hh.model_copy(update={"income": [bumped_inc, *hh.income[1:]]})

    fns_after = _by_program(screen_all(bumped), "fns")
    if fns_after.status == "likely_eligible":  # eligible -> ineligible is legitimate
        assert fns_after.estimated_benefit_cents <= fns_before.estimated_benefit_cents


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(eligible_fns_households(), _cents)
def test_fns_increasing_rent_never_lowers_allotment(hh: Household, bump: int):
    # Same shape as the dependent-care test, but through the shelter-deduction
    # path (excess-shelter computation and its non-elderly cap).
    fns_before = _by_program(screen_all(hh), "fns")
    assume(fns_before.status == "likely_eligible")

    exp = hh.expenses
    base_rent = exp.rent_or_mortgage_cents or 0
    bumped_exp = exp.model_copy(update={"rent_or_mortgage_cents": base_rent + bump})
    bumped = hh.model_copy(update={"expenses": bumped_exp})

    fns_after = _by_program(screen_all(bumped), "fns")
    assume(fns_after.status == "likely_eligible")
    assert fns_after.estimated_benefit_cents >= fns_before.estimated_benefit_cents


def test_income_limits_strictly_grow_with_household_size():
    """Every percent-of-FPL limit the engine screens against is strictly
    increasing in household size through 12 (covering the beyond-8
    additional-member extrapolation)."""
    from rules.tables.loader import load_table

    med = load_table("medicaid").values
    disregard = int(med["magi_disregard_pct"])
    effective_pcts = {
        int(med["adult_expansion_pct"]) + disregard,
        int(med["pregnant_pct"]) + disregard,
        int(med["child_chip_ceiling_pct"]) + disregard,
        int(med["parent_caretaker_pct"]) + disregard,
        *(int(p) + disregard for p in med["child_pct_by_age_band"].values()),
        int(load_table("wic").values["percent_of_fpl"]),
        int(load_table("lifeline").values["percent_of_fpl"]),
        200,  # FNS BBCE gross
    }
    for pct in sorted(effective_pcts):
        for size in range(1, 12):
            assert pct_of_fpl(pct, size + 1) > pct_of_fpl(pct, size), (
                f"{pct}% limit not increasing at size {size}"
            )


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


# ---------------------------------------------------------------------------
# 6. Cross-program invariants
# ---------------------------------------------------------------------------


@st.composite
def wic_adjunctive_households(draw) -> Household:
    """A WIC-categorical lone child whose gross income sits ABOVE the WIC 185%
    limit but at/under the children's-Medicaid CHIP ceiling (216% FPL), so
    Medicaid is likely_eligible while WIC fails its own income test.

    For a size-1 household: WIC limit = pct_of_fpl(185, 1), CHIP ceiling =
    pct_of_fpl(216, 1). Income drawn strictly between them forces the
    adjunctive pathway. The child's age (0..4) keeps WIC categorical.
    """
    wic_limit = pct_of_fpl(185, 1)
    chip_ceiling = pct_of_fpl(216, 1)
    income = draw(st.integers(min_value=wic_limit + 1, max_value=chip_ceiling))
    age = draw(st.integers(min_value=0, max_value=4))
    return Household(
        members=[
            Member(
                id="m1",
                age=age,
                relationship="self",
                is_pregnant=False,
                is_disabled=False,
                immigration_status="citizen",
                is_student=False,
            )
        ],
        income=[IncomeItem(id="i0", member_id="m1", kind="wages", amount_cents=income, frequency="monthly")],
        expenses=Expenses(),
        county="Wake",
        purchases_and_prepares_together=True,
    )


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(wic_adjunctive_households())
def test_wic_adjunctive_fires_when_medicaid_eligible_and_over_wic_income(hh: Household):
    result = screen_all(hh)
    wic = _by_program(result, "wic")
    medicaid = _by_program(result, "medicaid")
    fns = _by_program(result, "fns")

    # Precondition holds by construction: FNS or Medicaid is eligible and the
    # household's gross income exceeds the WIC limit.
    assert medicaid.status == "likely_eligible" or fns.status == "likely_eligible"
    gross = sum(i.amount_cents for i in hh.income)
    assert gross > pct_of_fpl(185, 1)

    # The invariant: WIC must catch this household adjunctively, not drop it.
    assert wic.status == "likely_eligible"
    assert any(r.rule_id == "wic.adjunctive" for r in wic.reasons)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(households())
def test_lifeline_never_income_resolves_while_fns_and_medicaid_undecided(hh: Household):
    """Lifeline must not reach an income-grounded verdict while both FNS and
    Medicaid are still needs_more_info.

    Concretely: whenever FNS and Medicaid are BOTH needs_more_info, Lifeline is
    never likely_ineligible (that verdict is the income test's negative
    outcome), and any likely_eligible it reports rests on definite evidence —
    reported SSI participation or its own complete, under-limit income test —
    never on an FNS/Medicaid pathway that has not itself resolved.
    """
    result = screen_all(hh)
    fns = _by_program(result, "fns")
    medicaid = _by_program(result, "medicaid")
    lifeline = _by_program(result, "lifeline")

    if fns.status == "needs_more_info" and medicaid.status == "needs_more_info":
        assert lifeline.status != "likely_ineligible"
        if lifeline.status == "likely_eligible":
            rule_ids = {r.rule_id for r in lifeline.reasons}
            # The FNS/Medicaid adjunctive wording would be dishonest here (both
            # are undecided), so eligibility must come from SSI or income.
            assert rule_ids <= {"lifeline.income", "lifeline.qualifying_program"}
            if rule_ids == {"lifeline.qualifying_program"}:
                assert any(i.kind == "ssi" for i in hh.income)
