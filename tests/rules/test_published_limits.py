"""Cross-checks engine-computed limits against the published dollar charts.

The Medicaid table stores base PERCENTAGES and the engine turns them into
dollar limits at screening time. These tests pin the engine's computed limits
to an independent transcription of the source chart's own dollar columns, so a
percentage typo, a disregard double-count, or an FPL mismatch fails loudly here
even when every table-level test passes. (The expansion-screened-at-143% bug
fixed in 24b5ed1 is exactly the class of error this file exists to catch: it
would have missed the chart by $66.40 at size 1.)

Chart transcribed 2026-07-03 from the MA-3321 PDF (REVISED 4/1/2026) at
rules/tables/medicaid.yaml's source_url. Sizes 1-10, whole dollars as printed
(the disregard row is printed to the cent). NC rounds each category's BASE
limit UP to the whole dollar, so the chart pins an engine limit to within $1,
not to the cent: assertions allow chart_total - engine in [-2, 101] cents.

Not transcribed on purpose: rows the engine does not screen (MAF-D 195%,
TMA 185%) and the chart's "Add'l" column (its disregard cell derives
differently than the size-9/10 columns; those columns already exercise the
additional-member method).
"""
from __future__ import annotations

from rules.programs._shared import pct_of_fpl
from rules.programs.medicaid import _limit, _maf_cn_limit
from rules.tables.loader import load_table

# MA-3321 base dollar limits by household size, integer cents. Keys 1-10.
_MXP_N_133 = {1: 176900, 2: 239900, 3: 302800, 4: 365800, 5: 428800,
              6: 491700, 7: 554700, 8: 617600, 9: 680600, 10: 743500}
_MPW_196 = {1: 260700, 2: 353500, 3: 446300, 4: 539000, 5: 631800,
            6: 724600, 7: 817400, 8: 910100, 9: 1002900, 10: 1095700}
_MIC_N_UNDER_1_194 = {1: 258100, 2: 349900, 3: 441700, 4: 533500, 5: 625400,
                      6: 717200, 7: 809000, 8: 900900, 9: 992700, 10: 1084500}
_MIC_N_1_5_141 = {1: 187600, 2: 254300, 3: 321100, 4: 387800, 5: 454500,
                  6: 521300, 7: 588000, 8: 654800, 9: 721500, 10: 788200}
_MIC_N_6_18_107 = {1: 142400, 2: 193000, 3: 243700, 4: 294300, 5: 344900,
                   6: 395600, 7: 446200, 8: 496900, 9: 547500, 10: 598200}
_MIC_1_CEILING_211 = {1: 280700, 2: 380600, 3: 480400, 4: 580300, 5: 680200,
                      6: 780000, 7: 879900, 8: 979800, 9: 1079700, 10: 1179500}
# MAF-C/N is a dollar need standard, not a percentage row (no % printed).
_MAF_C_N = {1: 43400, 2: 56900, 3: 66700, 4: 74400, 5: 82400,
            6: 90100, 7: 97500, 8: 103600, 9: 109600, 10: 116900}
# "5% Disregard" row, printed to the cent.
_DISREGARD_5PCT = {1: 6650, 2: 9017, 3: 11383, 4: 13750, 5: 16117,
                   6: 18483, 7: 20850, 8: 23217, 9: 25583, 10: 27950}


def test_chart_disregard_row_is_five_percent_of_our_fpl():
    """The chart's disregard row equals 5% of fpl.yaml's monthly values to the
    cent at every size (including 9-10, which exercises the additional-member
    extrapolation) — an independent confirmation that fpl.yaml matches the FPL
    figures NC used to build MA-3321."""
    for size in range(1, 11):
        assert _DISREGARD_5PCT[size] == pct_of_fpl(5, size), f"size {size}"


def test_engine_magi_limits_match_chart_dollars():
    """Every percentage-screened MAGI category: the engine's effective limit
    (base + 5% disregard, as _screen_member computes it) lands within the
    chart's whole-dollar rounding of the printed base + printed disregard."""
    values = load_table("medicaid").values
    categories = {
        "expansion (MXP-N)": (int(values["adult_expansion_pct"]), _MXP_N_133),
        "pregnant (MPW)": (int(values["pregnant_pct"]), _MPW_196),
        "child <1 (MIC-N)": (int(values["child_pct_by_age_band"]["under_1"]), _MIC_N_UNDER_1_194),
        "child 1-5 (MIC-N)": (int(values["child_pct_by_age_band"]["age_1_5"]), _MIC_N_1_5_141),
        "child 6-18 (MIC-N)": (int(values["child_pct_by_age_band"]["age_6_18"]), _MIC_N_6_18_107),
        "CHIP ceiling (MIC-1)": (int(values["child_chip_ceiling_pct"]), _MIC_1_CEILING_211),
    }
    disregard = int(values["magi_disregard_pct"])
    for label, (base_pct, chart) in categories.items():
        for size in range(1, 11):
            engine = _limit(base_pct, disregard, size)
            chart_total = chart[size] + _DISREGARD_5PCT[size]
            diff = chart_total - engine
            assert -2 <= diff <= 101, (
                f"{label} size {size}: engine {engine} vs chart {chart_total} "
                f"(diff {diff} cents exceeds whole-dollar rounding)"
            )


def test_engine_parent_caretaker_limit_matches_chart_exactly():
    """The engine screens parent/caretaker against the chart's MAF-C/N dollar
    standard directly (stored in medicaid.yaml), so unlike the ceiling-rounded
    percentage rows this one must match the chart TO THE CENT: printed dollars
    plus the printed disregard row at every size."""
    values = load_table("medicaid").values
    disregard = int(values["magi_disregard_pct"])
    for size in range(1, 11):
        engine = _maf_cn_limit(values, disregard, size)
        chart_total = _MAF_C_N[size] + _DISREGARD_5PCT[size]
        assert engine == chart_total, f"size {size}: engine {engine} != chart {chart_total}"
