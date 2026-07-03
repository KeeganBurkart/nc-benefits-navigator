"""Tests for the informational income_margin on ProgramResult.

Every expected number is hand-computed from rules/tables/*.yaml:
  FPL monthly: size1=133000 size2=180333
  FNS: gross 200% size1=266000; net 100% size1=130500; std deduction "1-2"=20900
  Medicaid: expansion (133+5)%*133000=183540; CHIP (211+5)%*133000=287280
  WIC: 185% size2 = round(180333*1.85)=333616
  Lifeline: 135% size1 = round(133000*1.35)=179550
"""
from __future__ import annotations

from rules.models import Household, IncomeItem, Member
from rules.programs.fns import evaluate as fns_evaluate
from rules.programs.lifeline import evaluate as lifeline_evaluate
from rules.programs.medicaid import evaluate as medicaid_evaluate
from rules.programs.wic import evaluate as wic_evaluate


def member(id, **kw):
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


def single_adult(amount_cents, **member_kw):
    return Household(
        members=[member("m1", **member_kw)],
        income=[income("i1", amount_cents)],
        purchases_and_prepares_together=True,
    )


# ---------------------------------------------------------------------------
# FNS
# ---------------------------------------------------------------------------

def test_fns_gross_margin_under_limit():
    # size 1, gross 200000 vs 266000 gross limit -> +66000 headroom.
    m = fns_evaluate(single_adult(200000)).income_margin
    assert m is not None
    assert m.limit_cents == 266000
    assert m.income_cents == 200000
    assert m.margin_cents == 66000
    assert "gross" in m.test_label and "household of 1" in m.test_label


def test_fns_gross_margin_over_limit_matches_ineligible():
    # gross 300000 > 266000 -> margin -34000 and the gross test fails.
    r = fns_evaluate(single_adult(300000))
    assert r.status == "likely_ineligible"
    assert r.income_margin is not None
    assert r.income_margin.margin_cents == -34000


def test_fns_elderly_margin_uses_net_test():
    # Age 70 waives the gross test. wages 100000: std 20900 + 20% earned 20000
    # -> net 59100; net limit size1 130500 -> +71400.
    r = fns_evaluate(single_adult(100000, age=70))
    m = r.income_margin
    assert r.status == "likely_eligible"
    assert m is not None
    assert m.limit_cents == 130500
    assert m.income_cents == 59100
    assert m.margin_cents == 71400
    assert "net" in m.test_label and "waived" in m.test_label


def test_fns_margin_none_when_income_incomplete():
    hh = Household(
        members=[member("m1")],
        income=[IncomeItem(id="i1", kind="wages", frequency="monthly")],  # no amount
        purchases_and_prepares_together=True,
    )
    assert fns_evaluate(hh).income_margin is None


# ---------------------------------------------------------------------------
# Medicaid
# ---------------------------------------------------------------------------

def test_medicaid_margin_expansion_adult():
    m = medicaid_evaluate(single_adult(100000)).income_margin
    assert m is not None
    assert m.limit_cents == 183540
    assert m.margin_cents == 83540
    assert "expansion" in m.test_label


def test_medicaid_margin_child_uses_chip_ceiling():
    hh = Household(
        members=[member("c1", age=3, relationship="child")],
        income=[income("i1", 100000)],
        purchases_and_prepares_together=True,
    )
    m = medicaid_evaluate(hh).income_margin
    assert m is not None
    assert m.limit_cents == 287280
    assert m.margin_cents == 187280
    assert "CHIP" in m.test_label


def test_medicaid_margin_present_on_fail_fast():
    # 900000 > every limit: fail-fast ineligible, margin -716460 vs expansion.
    r = medicaid_evaluate(single_adult(900000))
    assert r.status == "likely_ineligible"
    assert r.income_margin is not None
    assert r.income_margin.margin_cents == 183540 - 900000


def test_medicaid_margin_none_when_no_magi_category():
    # A lone 70-year-old has no MAGI category (ABD hand-off) -> no margin.
    r = medicaid_evaluate(single_adult(50000, age=70))
    assert r.status == "needs_more_info"
    assert r.income_margin is None


# ---------------------------------------------------------------------------
# WIC / Lifeline
# ---------------------------------------------------------------------------

def test_wic_margin_counts_pregnancy_in_size():
    # One pregnant member -> WIC size 2: limit 333616; income 300000 -> +33616.
    r = wic_evaluate(single_adult(300000, age=28, is_pregnant=True))
    m = r.income_margin
    assert r.status == "likely_eligible"
    assert m is not None
    assert m.limit_cents == 333616
    assert m.margin_cents == 33616
    assert "pregnancy" in m.test_label


def test_lifeline_margin_under_limit():
    r = lifeline_evaluate(single_adult(100000))
    m = r.income_margin
    assert r.status == "likely_eligible"
    assert m is not None
    assert m.limit_cents == 179550
    assert m.margin_cents == 79550


def test_lifeline_margin_negative_when_over_everything():
    r = lifeline_evaluate(single_adult(900000))
    assert r.status == "likely_ineligible"
    assert r.income_margin is not None
    assert r.income_margin.margin_cents == 179550 - 900000
