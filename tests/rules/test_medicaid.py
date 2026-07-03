"""Tests for rules/programs/medicaid.py — written before implementation (TDD).

Every expected number is hand-computed from the figures in
rules/tables/medicaid.yaml and rules/tables/fpl.yaml, with the arithmetic shown
in comments. All money is integer cents.

Reference values used below:
  FPL monthly_cents_by_household_size:
    1=133000 2=180333 3=227667 4=275000 5=322333 6=369667 7=417000 8=464333
    additional_member_cents = 47333
  Medicaid base percents (medicaid.yaml):
    adult_expansion_pct = 133   pregnant_pct = 196
    child_pct_by_age_band: under_1=194 age_1_5=141 age_6_18=107
    child_chip_ceiling_pct = 211
    parent_caretaker_pct = 33
    magi_disregard_pct = 5  (added to the base at screening)

  Effective limit = (base + 5)% * FPL_monthly[size].

  At SIZE 1 (FPL 133000):
    child under_1   = 199% * 133000 = 264670
    child age_1_5   = 146% * 133000 = 194180
    child age_6_18  = 112% * 133000 = 148960
    child CHIP      = 216% * 133000 = 287280
    pregnant        = 201% * 133000 = 267330
    parent/caretaker= 38%  * 133000 = 50540
    expansion adult = 138% * 133000 = 183540
"""
from __future__ import annotations

from rules.citations import cite
from rules.models import Expenses, Household, IncomeItem, Member

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def member(id, **kw):
    # default to a fully-specified citizen adult so unrelated fields never show
    # up as "missing" unless a test intends them to.
    base = dict(
        age=34,
        relationship="self",
        is_pregnant=False,
        is_disabled=False,
        immigration_status="citizen",
        is_student=False,
    )
    base.update(kw)
    return Member(id=id, **base)


def income(id, amount_cents, kind="wages", frequency="monthly", **kw):
    return IncomeItem(id=id, amount_cents=amount_cents, kind=kind, frequency=frequency, **kw)


def evaluate(hh):
    from rules.programs.medicaid import evaluate as _evaluate
    return _evaluate(hh)


def reasons_by_rule(result):
    return [r.rule_id for r in result.reasons]


# ---------------------------------------------------------------------------
# Program shape / metadata
# ---------------------------------------------------------------------------

def test_program_metadata():
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    r = evaluate(hh)
    assert r.program == "medicaid"
    assert r.program_label == "NC Medicaid"


def test_registered_in_PROGRAMS():
    from rules.programs import PROGRAMS
    assert "medicaid" in PROGRAMS
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    assert PROGRAMS["medicaid"](hh).program == "medicaid"


def test_result_is_json_serializable():
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    r = evaluate(hh)
    dumped = r.model_dump()
    assert dumped["program"] == "medicaid"
    assert isinstance(dumped["reasons"], list)
    for reason in dumped["reasons"]:
        assert set(reason["citation"]) >= {"rule_id", "manual", "section", "title", "url"}


def test_estimated_benefit_always_none():
    # Eligible child, ineligible adult, needs-more-info — benefit must be None each time.
    elig = Household(members=[member("c1", age=7, relationship="child")],
                     income=[income("i1", 50000)])
    inelig = Household(members=[member("m1")], income=[income("i1", 900000)])
    needs = Household(members=[Member(id="m1", immigration_status="citizen")])  # age None
    for hh in (elig, inelig, needs):
        assert evaluate(hh).estimated_benefit_cents is None


# ---------------------------------------------------------------------------
# Child age-band boundaries (size 1)
# ---------------------------------------------------------------------------

def test_child_under_1_at_limit_passes():
    # under_1 limit = 264670. income exactly 264670 → at limit → eligible.
    hh = Household(members=[member("c1", age=0, relationship="child")],
                   income=[income("i1", 264670)])
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.child" in reasons_by_rule(r)


def test_child_age_1_5_over_band_within_chip_window():
    # age 3 → age_1_5 base limit 194180. income 200000 is OVER band limit but
    # <= CHIP ceiling 287280 → still child-eligible at CHIP level.
    hh = Household(members=[member("c1", age=3, relationship="child")],
                   income=[income("i1", 200000)])
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.child" in reasons_by_rule(r)
    child_reason = next(x for x in r.reasons if x.rule_id == "medicaid.child")
    assert "CHIP" in child_reason.text or "Health Choice" in child_reason.text


def test_child_age_6_18_at_chip_ceiling_passes():
    # age 12 → age_6_18 base limit 148960. CHIP ceiling 287280.
    # income exactly 287280 = at CHIP ceiling → eligible (CHIP-level).
    hh = Household(members=[member("c1", age=12, relationship="child")],
                   income=[income("i1", 287280)])
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.child" in reasons_by_rule(r)


def test_child_over_chip_ceiling_fails():
    # age 12, income 287281 = one cent over CHIP ceiling → not child-eligible.
    # 34yo... no other member; child can't be parent/caretaker; not expansion (<19).
    # → no member eligible, nothing missing → likely_ineligible.
    hh = Household(members=[member("c1", age=12, relationship="child")],
                   income=[income("i1", 287281)])
    r = evaluate(hh)
    assert r.status == "likely_ineligible"


# ---------------------------------------------------------------------------
# Pregnant boundary (size 1)
# ---------------------------------------------------------------------------

def test_pregnant_at_limit_passes():
    # pregnant limit = 267330. income exactly 267330 → eligible.
    hh = Household(members=[member("m1", age=28, is_pregnant=True)],
                   income=[income("i1", 267330)])
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.pregnant" in reasons_by_rule(r)


def test_pregnant_one_cent_over_fails_to_expansion_then_ineligible():
    # pregnant limit 267330; income 267331 over pregnant limit. Member is 28 so
    # also tests expansion (138% = 183540) → over that too → ineligible.
    hh = Household(members=[member("m1", age=28, is_pregnant=True)],
                   income=[income("i1", 267331)])
    r = evaluate(hh)
    assert r.status == "likely_ineligible"


# ---------------------------------------------------------------------------
# Parent/caretaker boundary + dollar-standard caveat
# ---------------------------------------------------------------------------

def test_parent_caretaker_at_limit_passes_with_caveat():
    # parent/caretaker limit size 2 = 38% * 180333 = 68526.54 → 68527 (half-up).
    # Parent m1 (age 40) with child c1 (age 10). income 68000 <= 68527 → eligible
    # via parent/caretaker. The child c1 at age_6_18 CHIP ceiling 216% * 180333
    # = 389519.28 → 389519 — child also eligible, but to isolate the caveat we
    # make income low enough that BOTH pass; child is higher priority though, so
    # the household is eligible via the child. To force the parent/caretaker
    # pathway to be the deciding one, give an income above the child's limit but
    # below parent/caretaker — impossible (parent limit << child limit). So we
    # assert the caveat appears whenever the parent/caretaker reason is emitted.
    #
    # Construct: child is NOT present-as-child by making the only "child" 18 and
    # the parent eligible only via parent/caretaker is not separable. Instead we
    # assert the caveat text on the parent/caretaker reason directly: build a
    # household where parent qualifies and assert the reason text mentions a
    # dollar standard that varies / caseworker.
    #
    # size 2: parent m1 age 40, child c1 age 10. income 68000.
    #   parent limit = 68527 → 68000 <= limit → parent eligible.
    #   child age_6_18 CHIP 216% * 180333 = 389519 → 68000 <= limit → child eligible.
    hh = Household(
        members=[member("m1", age=40, relationship="self"),
                 member("c1", age=10, relationship="child")],
        income=[income("i1", 68000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.parent_caretaker" in reasons_by_rule(r)
    pc = next(x for x in r.reasons if x.rule_id == "medicaid.parent_caretaker")
    low = pc.text.lower()
    assert "dollar" in low and ("vary" in low or "varies" in low or "caseworker" in low)


def test_parent_caretaker_over_limit_but_child_still_eligible():
    # size 2: parent m1 age 40, child c1 age 10. income 100000.
    #   parent limit 68527 → 100000 over → parent NOT eligible via parent/caretaker.
    #   parent expansion 138% * 180333 = 248859.54 → 248860; 100000 <= that → parent
    #     eligible via EXPANSION instead.
    #   child CHIP 389519 → 100000 <= → child eligible.
    # → household eligible; parent/caretaker reason should NOT be the parent's.
    hh = Household(
        members=[member("m1", age=40, relationship="self"),
                 member("c1", age=10, relationship="child")],
        income=[income("i1", 100000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.expansion_adult" in reasons_by_rule(r)


# ---------------------------------------------------------------------------
# Expansion adult boundary (size 1)
# ---------------------------------------------------------------------------

def test_expansion_adult_at_limit_passes():
    # expansion limit size 1 = 183540. income exactly 183540 → eligible.
    hh = Household(members=[member("m1", age=34)],
                   income=[income("i1", 183540)])
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.expansion_adult" in reasons_by_rule(r)


def test_expansion_adult_one_cent_over_fails():
    # income 183541 over expansion limit. Not pregnant, no child → no category.
    # nothing missing → likely_ineligible.
    hh = Household(members=[member("m1", age=34)],
                   income=[income("i1", 183541)])
    r = evaluate(hh)
    assert r.status == "likely_ineligible"


# ---------------------------------------------------------------------------
# MAGI countable income asymmetry vs FNS
# ---------------------------------------------------------------------------

def test_ssi_counts_for_fns_but_not_medicaid():
    from rules.programs.fns import evaluate as fns_evaluate

    # Single adult, age 34. SSI income 250000/mo. SSI does NOT count for Medicaid.
    #   Medicaid countable income = 0 → expansion limit 183540 → 0 <= limit → eligible.
    # SSI DOES count as unearned income for FNS gross test.
    #   FNS size 1 gross limit = 266000; gross 250000 <= → passes gross.
    #   std "1-2" 20900, no earned ded (SSI unearned). net = 250000 - 20900 = 229100.
    #   net limit size 1 = 130500 → 229100 > limit → FNS likely_ineligible.
    hh = Household(members=[member("m1", age=34)],
                   income=[income("i1", 250000, kind="ssi")])
    med = evaluate(hh)
    fns = fns_evaluate(hh)
    assert med.status == "likely_eligible"        # SSI excluded → 0 countable
    assert fns.status == "likely_ineligible"      # SSI counted → fails net
    assert "medicaid.expansion_adult" in reasons_by_rule(med)


def test_child_support_received_excluded_from_magi():
    # Adult age 34. child_support_received 300000 (excluded) + wages 50000 (counts).
    # countable = 50000 → expansion 183540 → 50000 <= limit → eligible.
    hh = Household(
        members=[member("m1", age=34)],
        income=[income("i1", 50000, kind="wages"),
                income("i2", 300000, kind="child_support_received")],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.expansion_adult" in reasons_by_rule(r)


def test_child_support_counts_for_fns_but_not_medicaid():
    from rules.programs.fns import evaluate as fns_evaluate

    # Single adult, age 34. child_support_received 300000/mo, no other income.
    #   Medicaid: child support is excluded from MAGI → countable 0 → expansion
    #     limit 183540 → 0 <= limit → likely_eligible.
    #   FNS: ALL income counts toward gross. gross 300000 > size-1 gross limit
    #     266000 → fails the gross test → likely_ineligible.
    hh = Household(members=[member("m1", age=34)],
                   income=[income("i1", 300000, kind="child_support_received")])
    med = evaluate(hh)
    fns = fns_evaluate(hh)
    assert med.status == "likely_eligible"        # child support excluded → 0 countable
    assert fns.status == "likely_ineligible"      # child support counted → fails gross
    assert "medicaid.expansion_adult" in reasons_by_rule(med)


def test_noncountable_missing_amount_does_not_block():
    # SSI item with missing amount → irrelevant to Medicaid, must NOT block.
    # wages 50000 counts → expansion eligible.
    hh = Household(
        members=[member("m1", age=34)],
        income=[income("i1", 50000, kind="wages"),
                IncomeItem(id="i2", kind="ssi", frequency="monthly")],  # amount None
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "income[1].amount_cents" not in r.missing_fields


def test_countable_missing_amount_blocks():
    # wages item missing amount → countable item incomplete → needs_more_info.
    hh = Household(
        members=[member("m1", age=34)],
        income=[IncomeItem(id="i1", kind="wages", frequency="monthly")],  # amount None
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "income[0].amount_cents" in r.missing_fields


# ---------------------------------------------------------------------------
# 65+ aged/blind/disabled hand-off
# ---------------------------------------------------------------------------

def test_aged_alone_needs_more_info_with_abd_note():
    # single member age 70 → out of MAGI scope → ABD handoff → needs_more_info.
    hh = Household(members=[member("m1", age=70)],
                   income=[income("i1", 50000)])
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    # The household-size caveat and the ABD hand-off both cite medicaid.magi_income;
    # select the ABD one by its content (it speaks to the 65+/aged hand-off).
    abd = next(
        x for x in r.reasons
        if x.rule_id == "medicaid.magi_income"
        and ("65" in x.text or "older" in x.text.lower() or "aged" in x.text.lower())
    )
    low = abd.text.lower()
    assert "65" in abd.text or "older" in low or "aged" in low
    assert "different" in low or "does not" in low or "do not" in low


def test_aged_plus_eligible_child_is_eligible_with_advisory():
    # age 70 grandparent + age 8 grandchild (relationship child). income 50000.
    #   child eligible (well under CHIP). aged member → advisory ABD note.
    # → household likely_eligible (any-member rule) with the ABD advisory present.
    hh = Household(
        members=[member("g1", age=70, relationship="self"),
                 member("c1", age=8, relationship="child")],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.child" in reasons_by_rule(r)
    assert "medicaid.magi_income" in reasons_by_rule(r)  # ABD advisory still emitted


# ---------------------------------------------------------------------------
# Mixed immigration status
# ---------------------------------------------------------------------------

def test_not_qualified_member_emergency_only_others_unaffected():
    # m1 not_qualified adult (income 0), c1 citizen child age 8 eligible.
    # m1 gets emergency-only reason; c1 still eligible → household eligible.
    hh = Household(
        members=[member("m1", age=40, immigration_status="not_qualified"),
                 member("c1", age=8, relationship="child", immigration_status="citizen")],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.immigration" in reasons_by_rule(r)
    assert "medicaid.child" in reasons_by_rule(r)
    imm = next(x for x in r.reasons if x.rule_id == "medicaid.immigration")
    assert "emergency" in imm.text.lower()


def test_unknown_immigration_status_is_missing_field():
    hh = Household(
        members=[member("m1", age=34, immigration_status="unknown")],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "members[m1].immigration_status" in r.missing_fields


# ---------------------------------------------------------------------------
# Any-member eligibility
# ---------------------------------------------------------------------------

def test_one_eligible_child_among_ineligible_adults():
    # size 3: two adults each over expansion limit, one child clearly eligible.
    # size 3 FPL 227667. expansion 138% = 314180.46 → 314180.
    #   adults income high → over expansion. child CHIP 216% * 227667 = 491760.72
    #   → 491761. child income share low → eligible.
    # Put 400000 total income. expansion limit (size 3) 314180 → 400000 over → adults
    #   ineligible. child CHIP 491761 → 400000 <= → child eligible.
    hh = Household(
        members=[member("m1", age=40), member("m2", age=38, relationship="spouse"),
                 member("c1", age=9, relationship="child")],
        income=[income("i1", 400000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.child" in reasons_by_rule(r)


def test_no_member_eligible_nothing_missing_is_ineligible():
    # single adult age 34, income way over every limit → ineligible.
    hh = Household(members=[member("m1", age=34)],
                   income=[income("i1", 900000)])
    r = evaluate(hh)
    assert r.status == "likely_ineligible"


# ---------------------------------------------------------------------------
# Missing age / pregnant
# ---------------------------------------------------------------------------

def test_missing_age_blocks_with_missing_field():
    # age None → can't categorize → needs_more_info, missing members[m1].age.
    hh = Household(
        members=[Member(id="m1", immigration_status="citizen", is_pregnant=False)],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "members[m1].age" in r.missing_fields


def test_missing_pregnant_only_matters_in_income_window():
    # size 1. is_pregnant None.
    # income 200000: over expansion (183540) but <= pregnant (267330) → is_pregnant
    #   would change outcome → missing members[m1].is_pregnant.
    hh = Household(
        members=[Member(id="m1", age=28, relationship="self", is_disabled=False,
                        immigration_status="citizen", is_student=False)],  # is_pregnant None
        income=[income("i1", 200000)],
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "members[m1].is_pregnant" in r.missing_fields


def test_missing_pregnant_not_demanded_when_already_eligible():
    # income 100000 <= expansion 183540 → adult eligible regardless of pregnancy.
    # is_pregnant None must NOT be demanded.
    hh = Household(
        members=[Member(id="m1", age=28, relationship="self", is_disabled=False,
                        immigration_status="citizen", is_student=False)],  # is_pregnant None
        income=[income("i1", 100000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "members[m1].is_pregnant" not in r.missing_fields


def test_missing_pregnant_not_demanded_when_over_pregnant_limit():
    # income 300000 > pregnant limit 267330 → pregnancy cannot save them →
    # not demanded; adult also over expansion → ineligible.
    hh = Household(
        members=[Member(id="m1", age=28, relationship="self", is_disabled=False,
                        immigration_status="citizen", is_student=False)],  # is_pregnant None
        income=[income("i1", 300000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_ineligible"
    assert "members[m1].is_pregnant" not in r.missing_fields


def test_missing_pregnant_not_demanded_under_19():
    # 12yo child, is_pregnant None, income in adult window. Child eligibility does
    # not depend on pregnancy; must not demand is_pregnant.
    hh = Household(
        members=[Member(id="c1", age=12, relationship="child", is_disabled=False,
                        immigration_status="citizen", is_student=False)],  # is_pregnant None
        income=[income("i1", 200000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "members[c1].is_pregnant" not in r.missing_fields


# ---------------------------------------------------------------------------
# Fail-fast over the highest applicable limit
# ---------------------------------------------------------------------------

def test_fail_fast_over_highest_limit_with_missing_member_details():
    # size 1. Highest possible limit any member could reach is child CHIP 216% =
    # 287280. income 300000 > that → no member can qualify → likely_ineligible
    # even though the member's age is missing.
    hh = Household(
        members=[Member(id="m1", immigration_status="citizen")],  # age None
        income=[income("i1", 300000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_ineligible"


# ---------------------------------------------------------------------------
# Member descriptions (no ids in reason text)
# ---------------------------------------------------------------------------

def test_reason_describes_members_without_ids():
    hh = Household(members=[member("m1", age=34)],
                   income=[income("i1", 50000)])
    r = evaluate(hh)
    for reason in r.reasons:
        assert "m1" not in reason.text
        assert "medicaid." not in reason.text
    text = " ".join(x.text for x in r.reasons)
    assert "34-year-old" in text


def test_reason_describes_pregnant_and_child():
    hh = Household(
        members=[member("m1", age=28, is_pregnant=True),
                 member("c1", age=7, relationship="child")],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    text = " ".join(x.text for x in r.reasons)
    assert "pregnant" in text.lower()
    assert "7-year-old" in text


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_documents_always_identity_and_residency():
    hh = Household(members=[member("m1", age=34)], income=[income("i1", 50000)])
    r = evaluate(hh)
    rule_ids = [d.rule_id for d in r.required_documents]
    assert "doc.identity" in rule_ids
    assert "doc.residency" in rule_ids


def test_documents_one_per_countable_income_kind():
    hh = Household(
        members=[member("m1", age=34)],
        income=[income("i1", 50000, kind="wages"),
                income("i2", 30000, kind="wages"),
                income("i3", 20000, kind="social_security")],
    )
    r = evaluate(hh)
    names = [d.name for d in r.required_documents]
    assert names.count("Pay stubs (last 30 days)") == 1
    assert "Social Security award letter" in names


def test_documents_no_expense_docs():
    # MAGI has no deductions in v1 → never any expense docs even if expenses set.
    hh = Household(
        members=[member("m1", age=34)],
        income=[income("i1", 50000)],
        expenses=Expenses(rent_or_mortgage_cents=80000, dependent_care_cents=10000),
    )
    r = evaluate(hh)
    assert all(d.rule_id != "doc.expenses" for d in r.required_documents)


def test_documents_immigration_when_qualified_immigrant():
    hh = Household(
        members=[member("m1", age=34, immigration_status="qualified_immigrant")],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    assert "doc.immigration" in [d.rule_id for d in r.required_documents]


# ---------------------------------------------------------------------------
# Citations resolve and match for every reason emitted
# ---------------------------------------------------------------------------

def test_all_reason_citations_resolve_and_match():
    hh = Household(
        members=[member("m1", age=40, immigration_status="not_qualified"),
                 member("m2", age=70, relationship="other_relative"),
                 member("c1", age=7, relationship="child"),
                 member("p1", age=28, relationship="spouse", is_pregnant=True)],
        income=[income("i1", 50000)],
    )
    r = evaluate(hh)
    assert len(r.reasons) >= 1
    for reason in r.reasons:
        c = cite(reason.rule_id)  # must not raise
        assert reason.citation.rule_id == c.rule_id
        assert reason.citation.manual == c.manual
        assert reason.citation.section == c.section
        assert reason.citation.title == c.title
        assert reason.citation.url == c.url


def test_document_citations_resolve():
    hh = Household(
        members=[member("m1", age=34, immigration_status="qualified_immigrant")],
        income=[income("i1", 50000, kind="wages"),
                income("i2", 20000, kind="social_security")],
    )
    r = evaluate(hh)
    for doc in r.required_documents:
        cite(doc.rule_id)  # must not raise


# ---------------------------------------------------------------------------
# Reason text style
# ---------------------------------------------------------------------------

def test_reason_text_has_dollar_amounts_and_no_rule_ids():
    hh = Household(members=[member("m1", age=34)], income=[income("i1", 50000)])
    r = evaluate(hh)
    for reason in r.reasons:
        assert "medicaid." not in reason.text
    text = " ".join(x.text for x in r.reasons)
    assert "$" in text


# ---------------------------------------------------------------------------
# Pregnant adult with minor: priority 2 fires before priority 3
# ---------------------------------------------------------------------------

def test_pregnant_adult_with_minor_eligible_via_pregnant_not_parent_caretaker():
    # Verifies that a pregnant adult with a minor in the household is caught by
    # Priority 2 (pregnant) even though Priority 3 (parent/caretaker) would also
    # apply — i.e., has_minor=True does NOT reroute her to parent/caretaker first.
    #
    #   size 2, FPL[2] = 180333
    #   pregnant limit   = 201% * 180333 = 362,469.33 → 362,470 (half-up)
    #   parent/caretaker =  38% * 180333 =  68,526.54 →  68,527
    #
    # Income 100,000 is OVER the parent/caretaker limit (68,527) but well UNDER
    # the pregnant limit (362,470). If priorities were inverted, she would fall
    # through at priority 3 and reach expansion; instead priority 2 catches her.
    # The child (age 12) at CHIP ceiling 216% * 180333 = 389,519.28 → 389,519 is
    # also under the limit, so the household is eligible for two independent
    # reasons — but the pregnant reason must be present.
    hh = Household(
        members=[member("m1", age=28, is_pregnant=True),
                 member("c1", age=12, relationship="child")],
        income=[income("i1", 100000)],
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "medicaid.pregnant" in reasons_by_rule(r)
    assert "medicaid.parent_caretaker" not in reasons_by_rule(r)


# ---------------------------------------------------------------------------
# Household size beyond 8 (additional member)
# ---------------------------------------------------------------------------

def test_household_size_beyond_8_adds_additional_member():
    # size 9 = FPL[8] + additional = 464333 + 47333 = 511666.
    # child age 8 in unit; CHIP 216% * 511666 = 1105198.56 → 1105199.
    # income 500000 <= limit → child eligible (and expansion adults too).
    members_ = [member("m1", age=40)] + [
        member(f"c{i}", age=10, relationship="child") for i in range(2, 10)
    ]
    hh = Household(members=members_, income=[income("i1", 500000)])
    r = evaluate(hh)
    assert r.status == "likely_eligible"
