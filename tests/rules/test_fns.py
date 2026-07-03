"""Tests for rules/programs/fns.py — written before implementation (TDD).

Every expected number is hand-computed from the FY2026 figures in
rules/tables/fns.yaml, with the arithmetic shown in comments. All money is
integer cents.

Reference table values used below (from fns.yaml):
  gross_limit_200pct_cents:  1=266000 2=360667 3=455333 4=550000
  net_limit_100pct_cents:    1=130500 2=176300 3=222100 4=268000
  max_allotment_cents:       1=29800  2=54600  3=78500  4=99400
  standard_deduction_cents:  "1-2"=20900 "3"=20900 "4"=22300 "5"=26100 "6+"=29900
  earned_income_deduction_pct: 0.20
  excess_shelter_cap_cents:  74400
  standard_utility_allowance_cents: "1"=63700 "2"=69900 "3"=76800 "4"=83700 "5+"=91200
  medical_deduction_threshold_cents: 3500
  minimum_allotment_cents:   2400
"""
from __future__ import annotations

from rules.citations import cite
from rules.models import Expenses, Household, IncomeItem, Member

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def member(id, **kw):
    # default to a fully-specified citizen adult so unrelated fields never
    # show up as "missing" unless a test intends them to.
    base = dict(
        age=30,
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
    from rules.programs.fns import evaluate as _evaluate
    return _evaluate(hh)


def reasons_by_rule(result):
    return {r.rule_id for r in result.reasons}


# ---------------------------------------------------------------------------
# Program shape / metadata
# ---------------------------------------------------------------------------

def test_program_metadata():
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    r = evaluate(hh)
    assert r.program == "fns"
    assert r.program_label == "FNS (Food and Nutrition Services / SNAP)"


def test_registered_in_PROGRAMS():
    from rules.programs import PROGRAMS
    assert "fns" in PROGRAMS
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    assert PROGRAMS["fns"](hh).program == "fns"


def test_result_is_json_serializable():
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    r = evaluate(hh)
    dumped = r.model_dump()
    assert dumped["program"] == "fns"
    assert isinstance(dumped["reasons"], list)
    # citation must be embedded as plain data, not a dataclass
    for reason in dumped["reasons"]:
        assert set(reason["citation"]) >= {"rule_id", "manual", "section", "title", "url"}


# ---------------------------------------------------------------------------
# Gross income test boundary (single member, unit size 1)
# ---------------------------------------------------------------------------

def test_gross_exactly_at_limit_passes_gross():
    # unit size 1 gross limit = 266000. Income exactly 266000 → passes gross.
    # standard ded "1-2" = 20900; earned 20% of 266000 = 53200.
    # net = 266000 - 20900 - 53200 = 191900. net limit size 1 = 130500.
    # 191900 > 130500 → fails NET → likely_ineligible (no missing inputs:
    #   single member, no rent reported so shelter not pursued).
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 266000)],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    # gross passed; net failed
    assert "fns.gross_income" in reasons_by_rule(r)
    assert "fns.net_income" in reasons_by_rule(r)
    assert r.status == "likely_ineligible"


def test_gross_one_cent_over_fails_fast_even_with_missing_fields():
    # unit size 1 gross limit = 266000. Income 266001 = one cent over.
    # No elderly/disabled exemption → fail-fast likely_ineligible, even though
    # the member is missing 'age' (here we leave income incomplete elsewhere too).
    hh = Household(
        members=[Member(id="m1", immigration_status="citizen")],  # age missing
        income=[income("i1", 266001)],
    )
    r = evaluate(hh)
    assert r.status == "likely_ineligible"
    assert "fns.gross_income" in reasons_by_rule(r)
    # fail-fast: must NOT be needs_more_info despite missing age
    assert r.estimated_benefit_cents is None


# ---------------------------------------------------------------------------
# Elderly/disabled gross-test skip
# ---------------------------------------------------------------------------

def test_elderly_skips_gross_and_proceeds_to_net():
    # size 1, income 300000 (> gross limit 266000) but member age 67 → elderly.
    # Gross test skipped (exemption Reason). Proceed to net:
    #   standard "1-2" = 20900; earned 20% of 300000 = 60000.
    #   net = 300000 - 20900 - 60000 = 219100. net limit size 1 = 130500.
    #   219100 > 130500 → fails net → likely_ineligible, but gross was NOT the gate.
    hh = Household(
        members=[member("m1", age=67)],
        income=[income("i1", 300000)],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "fns.elderly_disabled_exemption" in reasons_by_rule(r)
    assert "fns.gross_income" not in reasons_by_rule(r)  # gross skipped entirely
    assert "fns.net_income" in reasons_by_rule(r)
    assert r.status == "likely_ineligible"


def test_disabled_skips_gross():
    hh = Household(
        members=[member("m1", age=40, is_disabled=True)],
        income=[income("i1", 300000)],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "fns.elderly_disabled_exemption" in reasons_by_rule(r)
    assert "fns.gross_income" not in reasons_by_rule(r)


# ---------------------------------------------------------------------------
# Eligible end-to-end with allotment
# ---------------------------------------------------------------------------

def test_eligible_household_with_allotment():
    # size 3, all wages, monthly income 200000 ($2,000).
    # gross limit size 3 = 455333 → 200000 <= limit → passes gross.
    # standard "3" = 20900; earned 20% of 200000 = 40000.
    # no shelter (no rent reported). net = 200000 - 20900 - 40000 = 139100.
    # net limit size 3 = 222100 → 139100 <= limit → passes net → eligible.
    # allotment = max_allotment[3]=78500 - 0.3*139100 (=41730) = 36770
    #           -> round down to whole dollar (FNS-360 step 28) = 36700.
    # size 3 > 2 so no minimum floor applies. 36700 > 0.
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 200000)],
        expenses=Expenses(),
        purchases_and_prepares_together=True,
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert r.estimated_benefit_cents == 36700
    assert "fns.gross_income" in reasons_by_rule(r)
    assert "fns.net_income" in reasons_by_rule(r)
    assert "fns.allotment" in reasons_by_rule(r)


# ---------------------------------------------------------------------------
# Individual deductions — each isolated, asserting the net delta
# ---------------------------------------------------------------------------

def test_dependent_care_deduction_changes_net():
    # size 3, wages 200000. dependent_care 30000.
    # baseline net (no dep care) = 200000 - 20900(std) - 40000(earned) = 139100.
    # with dep care: net = 139100 - 30000 = 109100.
    # allotment = 78500 - 0.3*109100 (=32730) = 45770 -> whole-dollar floor = 45700.
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 200000)],
        expenses=Expenses(dependent_care_cents=30000),
        purchases_and_prepares_together=True,
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "fns.deductions.dependent_care" in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 45700  # net 109100 → floor(78500-32730)


def test_child_support_paid_deduction_changes_net():
    # size 3, wages 200000. child_support_paid 25000.
    # net = 139100 - 25000 = 114100. allotment = 78500 - 0.3*114100 (=34230)
    #     = 44270 -> whole-dollar floor = 44200.
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 200000)],
        expenses=Expenses(child_support_paid_cents=25000),
        purchases_and_prepares_together=True,
    )
    r = evaluate(hh)
    assert "fns.deductions.child_support" in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 44200


def test_earned_income_deduction_only_on_earned_kinds():
    # size 1, unemployment 100000 (UNEARNED → no 20% deduction).
    # std "1-2" = 20900; no earned deduction. net = 100000 - 20900 = 79100.
    # net limit size 1 = 130500 → passes. allotment = 29800 - 0.3*79100 (=23730)
    #   = 6070 -> whole-dollar floor = 6000. size 1 <= 2 → min 2400; 6000 > 2400 keep.
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 100000, kind="unemployment")],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    # earned income deduction reason must NOT appear (no earned income)
    assert "fns.deductions.earned_income" not in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 6000


def test_medical_deduction_requires_elderly_and_over_threshold():
    # size 1, elderly (age 70), wages 90000, medical 13500.
    # medical deductible = 13500 - 3500 = 10000.
    # std "1-2"=20900; earned 20% of 90000 = 18000; medical 10000.
    # net = 90000 - 20900 - 18000 - 10000 = 41100.
    # net limit size 1 = 130500 → passes (gross skipped: elderly).
    # allotment = 29800 - 0.3*41100 (=12330) = 17470 -> whole-dollar floor = 17400.
    hh = Household(
        members=[member("m1", age=70)],
        income=[income("i1", 90000)],
        expenses=Expenses(medical_expenses_elderly_disabled_cents=13500),
    )
    r = evaluate(hh)
    assert "fns.deductions.medical" in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 17400


def test_medical_deduction_skipped_when_not_elderly_disabled():
    # size 1, age 40 (NOT elderly/disabled), wages 90000, medical 13500.
    # medical deduction does not apply. net = 90000 - 20900 - 18000 = 51100.
    # allotment = 29800 - 0.3*51100 (=15330) = 14470 -> whole-dollar floor = 14400.
    hh = Household(
        members=[member("m1", age=40)],
        income=[income("i1", 90000)],
        expenses=Expenses(medical_expenses_elderly_disabled_cents=13500),
    )
    r = evaluate(hh)
    assert "fns.deductions.medical" not in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 14400


def test_medical_at_or_below_threshold_not_deducted():
    # medical exactly 3500 (== threshold) → not > threshold → no deduction.
    # size 1 elderly, wages 90000. net = 90000 - 20900 - 18000 = 51100.
    # allotment = floor(29800 - 15330 = 14470) = 14400.
    hh = Household(
        members=[member("m1", age=70)],
        income=[income("i1", 90000)],
        expenses=Expenses(medical_expenses_elderly_disabled_cents=3500),
    )
    r = evaluate(hh)
    assert "fns.deductions.medical" not in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 14400


# ---------------------------------------------------------------------------
# Excess shelter deduction
# ---------------------------------------------------------------------------

def test_shelter_included_only_when_pays_heating_cooling():
    # size 1, wages 90000, rent 100000, pays_heating_cooling False (no SUA).
    # income after non-shelter deductions = 90000 - 20900 - 18000 = 51100.
    # shelter = rent only = 100000 (no SUA).
    # half of 51100 = 25550. excess = 100000 - 25550 = 74450.
    # NOT elderly/disabled → cap at 74400. capped excess = 74400.
    # net = 51100 - 74400 = floor 0. net limit 130500 → passes.
    # allotment = 29800 - round(0.3*0=0) = 29800. size1<=2, > min, keep 29800.
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 90000)],
        expenses=Expenses(rent_or_mortgage_cents=100000, pays_heating_cooling=False,
                          utilities_included=False),
    )
    r = evaluate(hh)
    assert "fns.deductions.shelter" in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 29800


def test_shelter_includes_sua_when_pays_heating_cooling():
    # size 1, wages 90000, rent 100000, pays_heating_cooling True → SUA "1"=63700.
    # income after non-shelter deductions = 51100 (as above).
    # shelter = 100000 + 63700 = 163700. half income = 25550.
    # excess = 163700 - 25550 = 138150. NOT elderly → cap 74400. capped = 74400.
    # net = 51100 - 74400 = floor 0. allotment = 29800.
    # Same benefit as previous test, but shelter is larger (cap binds either way).
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 90000)],
        expenses=Expenses(rent_or_mortgage_cents=100000, pays_heating_cooling=True,
                          utilities_included=False),
    )
    r = evaluate(hh)
    assert "fns.deductions.shelter" in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 29800


def test_shelter_uncapped_for_elderly():
    # size 1 elderly (age 70), wages 90000, rent 100000, no SUA (pays h/c False).
    # gross skipped. income after non-shelter deductions = 90000-20900-18000=51100.
    # shelter = 100000. half income = 25550. excess = 100000 - 25550 = 74450.
    # elderly → UNCAPPED → deduct full 74450.
    # net = 51100 - 74450 = floor 0. net limit 130500 → passes.
    # allotment = 29800 - 0 = 29800.
    hh = Household(
        members=[member("m1", age=70)],
        income=[income("i1", 90000)],
        expenses=Expenses(rent_or_mortgage_cents=100000, pays_heating_cooling=False,
                          utilities_included=False),
    )
    r = evaluate(hh)
    assert "fns.deductions.shelter" in reasons_by_rule(r)
    # Net floors to 0 in both capped and uncapped here, so to *prove* uncapping
    # we use a separate test below with a measurable difference.
    assert r.estimated_benefit_cents == 29800


def test_shelter_cap_vs_uncap_measurable_difference():
    # Construct a case where capped vs uncapped gives different net.
    # size 1, wages 60000.
    # non-shelter deductions: std 20900 + earned 20% of 60000=12000 → 32900.
    # income after = 60000 - 32900 = 27100. half = 13550.
    # rent = 90000, no SUA. shelter = 90000. excess = 90000 - 13550 = 76450.
    #
    # NON-ELDERLY: capped at 74400 → net = 27100 - 74400 = floor 0 → allotment 29800.
    # ELDERLY: uncapped 76450 → net = 27100 - 76450 = floor 0 → allotment 29800.
    # Both floor to 0 again — net is already tiny. So instead lower rent so the
    # cap difference shows above the floor:
    #
    # rent = 50000, no SUA. shelter = 50000. excess = 50000 - 13550 = 36450 (< cap),
    # so cap doesn't bind; both equal. Not useful either.
    #
    # The only way the cap visibly bites is when excess > 74400 AND net stays > 0
    # AND income-after-shelter > net_limit comparison still passes. With size 1
    # the net limit is 130500 and incomes here are small, so net floors to 0.
    # We therefore prove cap behavior at a LARGER unit where income is higher.
    #
    # size 4, wages 300000.
    # std "4"=22300; earned 20% of 300000=60000. non-shelter = 82300.
    # income after = 300000 - 82300 = 217700. half = 108850.
    # rent = 250000, no SUA. shelter = 250000. excess = 250000 - 108850 = 141150.
    # NON-ELDERLY cap 74400: net = 217700 - 74400 = 143300.
    #   net limit size4 = 268000 → passes. allotment = 99400 - 0.3*143300 (=42990)
    #     = 56410 -> whole-dollar floor = 56400.
    # ELDERLY uncapped 141150: net = 217700 - 141150 = 76550.
    #   allotment = 99400 - 0.3*76550 (=22965) = 76435 -> whole-dollar floor = 76400.
    members_nonelderly = [
        member("m1"), member("m2", relationship="spouse"),
        member("m3", age=10, relationship="child"),
        member("m4", age=8, relationship="child"),
    ]
    hh_capped = Household(
        members=members_nonelderly,
        income=[income("i1", 300000)],
        expenses=Expenses(rent_or_mortgage_cents=250000, pays_heating_cooling=False,
                          utilities_included=False),
        purchases_and_prepares_together=True,
    )
    r_capped = evaluate(hh_capped)
    assert r_capped.status == "likely_eligible"
    assert r_capped.estimated_benefit_cents == 56400

    members_elderly = [
        member("m1", age=67), member("m2", relationship="spouse"),
        member("m3", age=10, relationship="child"),
        member("m4", age=8, relationship="child"),
    ]
    hh_uncapped = Household(
        members=members_elderly,
        income=[income("i1", 300000)],
        expenses=Expenses(rent_or_mortgage_cents=250000, pays_heating_cooling=False,
                          utilities_included=False),
        purchases_and_prepares_together=True,
    )
    r_uncapped = evaluate(hh_uncapped)
    assert r_uncapped.status == "likely_eligible"
    assert r_uncapped.estimated_benefit_cents == 76400


# ---------------------------------------------------------------------------
# Allotment math edge cases
# ---------------------------------------------------------------------------

def test_allotment_rounds_down_to_whole_dollar():
    # FNS-360 worksheet step 28: subtract 30% of net from the max allotment and
    # round the result DOWN to the whole dollar (the manual's own example:
    # $192 - $30.10 = $161.90, round down to $161).
    # size 3 unemployment A. net = A - 20900 (std "3"). net = 100015 →
    #   0.3*100015 = 30004.5; 78500 - 30004.5 = 48495.5 -> floor to dollar = 48400.
    # A = 100015 + 20900 = 120915. net limit size3 = 222100 → passes.
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 120915, kind="unemployment")],
        expenses=Expenses(),
        purchases_and_prepares_together=True,
    )
    r = evaluate(hh)
    # net = 120915 - 20900 = 100015; floor((78500 - 30004.5)/100)*100 = 48400.
    assert r.estimated_benefit_cents == 48400
    assert r.estimated_benefit_cents % 100 == 0  # benefits are whole dollars


def test_minimum_allotment_floor_for_size_one():
    # size 1 unemployment, net high enough that computed allotment < minimum 2400.
    # We want 29800 - round(0.3*net) in (0, 2400). round(0.3*net) in (27400, 29800).
    # pick 0.3*net = 28000 → net ≈ 93333.33. round(0.3*93334)=28000.2→28000.
    # Easier: choose net so allotment computes to e.g. 1000, then min floors to 2400.
    # net = 96000: 0.3*96000 = 28800 → allotment = 29800 - 28800 = 1000 < 2400.
    # → floor to 2400. unemployment so no earned ded; net = A - 20900 = 96000 →
    #   A = 116900. net limit size1 = 130500 → 96000 <= limit → passes.
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 116900, kind="unemployment")],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    # computed = 29800 - 28800 = 1000; below minimum 2400 → floored to 2400.
    assert r.estimated_benefit_cents == 2400


def test_minimum_allotment_when_computation_goes_negative():
    # An eligible 1-2 person unit ALWAYS receives at least the minimum allotment
    # (7 CFR 273.10(e)(2)(ii)(C); FNS-360: "All one and two-person FNS units must
    # receive a minimum monthly allotment of $24").
    # size 1, net = 130500 (== net limit, passes): 0.3*130500 = 39150 →
    #   29800 - 39150 = -9350 → floor 0 → minimum 2400 applies.
    # net = A - 20900 (unemployment) = 130500 → A = 151400.
    # gross check size1 limit 266000 → 151400 <= 266000 passes gross too.
    # (A zero allotment with a passing net test is impossible at sizes 3+ with
    # the FY2026 tables: max_allotment >= 0.3 * net_limit at every such size.
    # If a future table flipped that, the engine reports the $0 computation as
    # a denial per 7 CFR 273.10(e)(2)(ii)(B).)
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 151400, kind="unemployment")],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert r.estimated_benefit_cents == 2400


# ---------------------------------------------------------------------------
# Mixed-status household
# ---------------------------------------------------------------------------

def test_not_qualified_member_shrinks_unit_but_income_counts():
    # 3 members; m3 is not_qualified → unit size = 2 (m1, m2), but ALL income counts.
    # m1 wages 150000, m3 wages 80000. total income = 230000.
    # unit size 2: gross limit 360667 → 230000 <= limit → passes gross.
    # std "1-2" (size 2) = 20900; earned 20% of 230000 = 46000.
    # net = 230000 - 20900 - 46000 = 163100. net limit size2 = 176300 → passes.
    # allotment = max_allot[2]=54600 - 0.3*163100 (=48930) = 5670 -> whole-dollar
    #   floor = 5600. size 2 <= 2 → min 2400; 5600 > 2400 keep.
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", relationship="other_relative", immigration_status="not_qualified")],
        income=[income("i1", 150000), income("i3", 80000, member_id="m3")],
        expenses=Expenses(),
        purchases_and_prepares_together=True,
    )
    r = evaluate(hh)
    assert "fns.immigration" in reasons_by_rule(r)
    assert r.status == "likely_eligible"
    assert r.estimated_benefit_cents == 5600


def test_unknown_immigration_status_is_missing_field():
    hh = Household(
        members=[member("m1", immigration_status="unknown")],
        income=[income("i1", 100000)],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "members[m1].immigration_status" in r.missing_fields


# ---------------------------------------------------------------------------
# Unit size beyond 10 (extrapolation)
# ---------------------------------------------------------------------------

def test_unit_size_beyond_10_extrapolates():
    # size 12. Extrapolation uses size-9→size-10 increments:
    #   gross_limit:   size10=1118000, size9=1023333, diff=94667.
    #                  size12 = 1118000 + 2*94667 = 1307334.
    #   net_limit:     size10=543100,  size9=497200,  diff=45900.
    #                  size12 = 543100 + 2*45900 = 634900.
    #   max_allotment: size10=222500,  size9=200700,  diff=21800.
    #                  size12 = 222500 + 2*21800 = 266100.
    #
    # income=200000 all wages. std band "6+"=29900. earned 20%=40000.
    # net = 200000 - 29900 - 40000 = 130100. net_limit=634900 → passes.
    # allotment = 266100 - 0.3*130100 (=39030) = 227070 -> whole-dollar floor = 227000.
    members_ = [member(f"m{i}", age=30 if i == 1 else 10,
                       relationship="self" if i == 1 else "child") for i in range(1, 13)]
    hh = Household(
        members=members_,
        income=[income("i1", 200000)],
        expenses=Expenses(),
        purchases_and_prepares_together=True,
    )
    r = evaluate(hh)
    assert r.status == "likely_eligible"
    assert "fns.gross_income" in reasons_by_rule(r)
    assert r.estimated_benefit_cents == 227000


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

def test_documents_always_identity_and_residency():
    hh = Household(members=[member("m1")], income=[income("i1", 100000)])
    r = evaluate(hh)
    rule_ids = [d.rule_id for d in r.required_documents]
    assert "doc.identity" in rule_ids
    assert "doc.residency" in rule_ids


def test_documents_one_per_income_kind():
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse")],
        income=[
            income("i1", 100000, kind="wages"),
            income("i2", 50000, kind="ssi", member_id="m2"),
            income("i3", 30000, kind="wages"),  # second wages → still one wages doc
        ],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    names = [d.name for d in r.required_documents]
    assert "Pay stubs (last 30 days)" in names
    assert "SSI award letter" in names
    # only ONE pay stub doc despite two wages items
    assert names.count("Pay stubs (last 30 days)") == 1


def test_documents_expense_verification_per_deduction():
    # claim dependent care + child support → expect those expense docs.
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 200000)],
        expenses=Expenses(dependent_care_cents=30000, child_support_paid_cents=25000),
    )
    r = evaluate(hh)
    expense_names = [d.name for d in r.required_documents if d.rule_id == "doc.expenses"]
    assert any("dependent care" in n.lower() for n in expense_names)
    assert any("child support" in n.lower() for n in expense_names)


def test_documents_immigration_when_qualified_immigrant():
    hh = Household(
        members=[member("m1", immigration_status="qualified_immigrant")],
        income=[income("i1", 100000)],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "doc.immigration" in [d.rule_id for d in r.required_documents]


# ---------------------------------------------------------------------------
# Citations resolve and match for every reason emitted
# ---------------------------------------------------------------------------

def test_all_reason_citations_resolve_and_match():
    # exercise a rich scenario that emits many reasons.
    hh = Household(
        members=[member("m1", age=67), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 150000)],
        expenses=Expenses(rent_or_mortgage_cents=80000, pays_heating_cooling=True,
                          utilities_included=False, dependent_care_cents=10000,
                          child_support_paid_cents=5000,
                          medical_expenses_elderly_disabled_cents=10000),
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
        members=[member("m1", immigration_status="qualified_immigrant")],
        income=[income("i1", 100000)],
        expenses=Expenses(rent_or_mortgage_cents=80000, pays_heating_cooling=True,
                          utilities_included=False),
    )
    r = evaluate(hh)
    for doc in r.required_documents:
        cite(doc.rule_id)  # must not raise


# ---------------------------------------------------------------------------
# Reason text style (dollars interpolated, no rule ids)
# ---------------------------------------------------------------------------

def test_reason_text_has_dollar_amounts_and_no_rule_ids():
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse"),
                 member("m3", age=5, relationship="child")],
        income=[income("i1", 200000)],
        expenses=Expenses(),
    )
    r = evaluate(hh)
    for reason in r.reasons:
        assert "fns." not in reason.text  # no rule ids leaked into client text
    # gross reason should mention dollars
    gross = next(x for x in r.reasons if x.rule_id == "fns.gross_income")
    assert "$" in gross.text


# ---------------------------------------------------------------------------
# needs_more_info paths
# ---------------------------------------------------------------------------

def test_empty_household_needs_more_info():
    hh = Household()
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert r.estimated_benefit_cents is None


def test_partial_income_needs_more_info_with_income_fields():
    # one income item missing amount and frequency → those are the missing fields.
    hh = Household(
        members=[member("m1")],
        income=[IncomeItem(id="i1", kind="wages")],  # amount + frequency missing
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "income[0].amount_cents" in r.missing_fields
    assert "income[0].frequency" in r.missing_fields


def test_hourly_income_missing_hours_is_missing_field():
    hh = Household(
        members=[member("m1")],
        income=[IncomeItem(id="i1", kind="wages", amount_cents=2000, frequency="hourly")],
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "income[0].hours_per_week" in r.missing_fields


# ---------------------------------------------------------------------------
# purchases_and_prepares_together
# ---------------------------------------------------------------------------

def test_pnp_none_multi_member_is_missing_field():
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse")],
        income=[income("i1", 100000)],
        purchases_and_prepares_together=None,
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "purchases_and_prepares_together" in r.missing_fields
    assert r.status == "needs_more_info"


def test_pnp_none_single_member_not_missing():
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 100000)],
        purchases_and_prepares_together=None,
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "purchases_and_prepares_together" not in r.missing_fields


def test_pnp_false_adds_limitation_reason():
    hh = Household(
        members=[member("m1"), member("m2", relationship="spouse")],
        income=[income("i1", 100000)],
        purchases_and_prepares_together=False,
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "fns.household_composition" in reasons_by_rule(r)


def test_pnp_false_irrelevant_for_single_member():
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 100000)],
        purchases_and_prepares_together=False,
        expenses=Expenses(),
    )
    r = evaluate(hh)
    assert "fns.household_composition" not in reasons_by_rule(r)


# ---------------------------------------------------------------------------
# Missing rent blocks net test (when gross passed) but not when gross failed
# ---------------------------------------------------------------------------

def test_missing_rent_blocks_net_when_gross_passes():
    # size 1, wages 100000 (passes gross). Member reports they pay heating/cooling
    # but rent is None → rent needed for net test → needs_more_info.
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 100000)],
        expenses=Expenses(pays_heating_cooling=True),  # rent None
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "expenses.rent_or_mortgage_cents" in r.missing_fields


def test_pays_heating_cooling_none_with_rent_is_missing():
    # rent set but pays_heating_cooling None → can't compute SUA → missing field.
    hh = Household(
        members=[member("m1")],
        income=[income("i1", 100000)],
        expenses=Expenses(rent_or_mortgage_cents=80000),  # pays_heating_cooling None
    )
    r = evaluate(hh)
    assert r.status == "needs_more_info"
    assert "expenses.pays_heating_cooling" in r.missing_fields
