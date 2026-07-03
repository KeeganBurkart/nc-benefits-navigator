"""Tests for the versioned program-data tables (Task 3).

These tests assert the loader contract and validate that every sourced
FY2026/CY2026 figure is present, well-typed, and internally consistent.
A human verifies the actual numbers against the cited sources; these tests
guard structure and invariants.
"""

from __future__ import annotations

import textwrap
import types
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from rules.tables.loader import (
    StaleTableError,
    Table,
    assert_current,
    load_table,
)

# ---------------------------------------------------------------------------
# Loader contract
# ---------------------------------------------------------------------------


def test_load_table_returns_typed_table() -> None:
    table = load_table("fpl")
    assert isinstance(table, Table)
    assert isinstance(table.values, (dict, types.MappingProxyType))
    assert isinstance(table.source_url, str) and table.source_url.startswith("http")
    assert isinstance(table.source_name, str) and table.source_name
    assert isinstance(table.effective_from, date)
    assert isinstance(table.effective_to, date)
    assert table.effective_from < table.effective_to


def test_table_is_frozen() -> None:
    table = load_table("fns")
    with pytest.raises(Exception):
        table.source_url = "http://example.com"  # type: ignore[misc]


def test_loader_caches_same_instance() -> None:
    assert load_table("medicaid") is load_table("medicaid")


def test_unknown_table_name_raises_clear_error() -> None:
    with pytest.raises(FileNotFoundError) as exc:
        load_table("does_not_exist")
    assert "does_not_exist" in str(exc.value)


def test_table_name_is_filename_stem() -> None:
    for name in ("fpl", "fns", "medicaid"):
        assert load_table(name) is not None


# ---------------------------------------------------------------------------
# assert_current / StaleTableError
# ---------------------------------------------------------------------------


def test_assert_current_passes_for_today() -> None:
    for name in ("fpl", "fns", "medicaid"):
        assert_current(load_table(name), date(2026, 6, 12))  # must not raise


def test_assert_current_raises_for_out_of_range_date() -> None:
    fns = load_table("fns")
    # fns effective range is 2025-10-01 .. 2026-09-30; a 2030 date is stale.
    with pytest.raises(StaleTableError) as exc:
        assert_current(fns, date(2030, 1, 1))
    msg = str(exc.value)
    assert "fns" in msg
    assert str(fns.effective_to) in msg


def test_assert_current_raises_before_range() -> None:
    fns = load_table("fns")
    with pytest.raises(StaleTableError):
        assert_current(fns, date(2020, 1, 1))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_Mapping = (dict, types.MappingProxyType)


def _all_positive_int_cents(node: object) -> bool:
    """Recursively assert every key ending in `_cents` holds a positive int."""
    if isinstance(node, _Mapping):
        for k, v in node.items():
            if isinstance(k, str) and k.endswith("_cents"):
                if isinstance(v, _Mapping):
                    if not _all_positive_int_cents(v):
                        return False
                else:
                    if not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
                        return False
            elif isinstance(v, _Mapping):
                if not _all_positive_int_cents(v):
                    return False
    return True


# ---------------------------------------------------------------------------
# FPL table
# ---------------------------------------------------------------------------

FPL_REQUIRED_KEYS = {
    "monthly_cents_by_household_size",
    "annual_cents_by_household_size",
    "additional_member_cents",
    "additional_member_annual_cents",
}


def test_fpl_has_all_required_keys() -> None:
    v = load_table("fpl").values
    assert FPL_REQUIRED_KEYS <= set(v)


def test_fpl_per_size_keys_are_1_through_8() -> None:
    v = load_table("fpl").values
    for key in ("monthly_cents_by_household_size", "annual_cents_by_household_size"):
        assert set(v[key]) == set(range(1, 9)), key


def test_fpl_all_cents_positive_ints() -> None:
    v = load_table("fpl").values
    assert _all_positive_int_cents(v)
    assert isinstance(v["additional_member_cents"], int) and v["additional_member_cents"] > 0
    assert (
        isinstance(v["additional_member_annual_cents"], int)
        and v["additional_member_annual_cents"] > 0
    )


def test_fpl_monthly_equals_annual_over_twelve_half_up() -> None:
    v = load_table("fpl").values
    monthly = v["monthly_cents_by_household_size"]
    annual = v["annual_cents_by_household_size"]
    for size in range(1, 9):
        expected = int(
            (Decimal(annual[size]) / Decimal(12)).to_integral_value(rounding=ROUND_HALF_UP)
        )
        assert monthly[size] == expected, f"size {size}: {monthly[size]} != {expected}"
    # additional-member figure obeys the same relation
    expected_add = int(
        (Decimal(v["additional_member_annual_cents"]) / Decimal(12)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    assert v["additional_member_cents"] == expected_add


def test_fpl_monotonic_by_size() -> None:
    annual = load_table("fpl").values["annual_cents_by_household_size"]
    for size in range(1, 8):
        assert annual[size + 1] > annual[size]


# ---------------------------------------------------------------------------
# FNS table
# ---------------------------------------------------------------------------

FNS_REQUIRED_KEYS = {
    "gross_limit_200pct_cents",
    "net_limit_100pct_cents",
    "max_allotment_cents",
    "standard_deduction_cents",
    "earned_income_deduction_pct",
    "excess_shelter_cap_cents",
    "homeless_shelter_deduction_cents",
    "standard_utility_allowance_cents",
    "medical_deduction_threshold_cents",
    "minimum_allotment_cents",
}


def test_fns_has_all_required_keys() -> None:
    v = load_table("fns").values
    assert FNS_REQUIRED_KEYS <= set(v)


def test_fns_per_size_keys_are_1_through_10() -> None:
    v = load_table("fns").values
    for key in ("gross_limit_200pct_cents", "net_limit_100pct_cents", "max_allotment_cents"):
        assert set(v[key]) == set(range(1, 11)), key


def test_fns_earned_income_deduction_pct() -> None:
    assert load_table("fns").values["earned_income_deduction_pct"] == 0.20


def test_fns_medical_deduction_threshold() -> None:
    assert load_table("fns").values["medical_deduction_threshold_cents"] == 3500


def test_fns_all_cents_positive_ints() -> None:
    assert _all_positive_int_cents(load_table("fns").values)


def test_fns_max_allotment_increases_with_size() -> None:
    allot = load_table("fns").values["max_allotment_cents"]
    for size in range(1, 10):
        assert allot[size + 1] > allot[size], f"allotment not increasing at size {size}"


def test_fns_gross_limit_exceeds_net_limit_per_size() -> None:
    v = load_table("fns").values
    gross = v["gross_limit_200pct_cents"]
    net = v["net_limit_100pct_cents"]
    for size in range(1, 11):
        assert gross[size] > net[size], f"gross !> net at size {size}"


def test_fns_gross_limit_is_exactly_200pct_of_fpl_annual() -> None:
    """NC BBCE gross limit equals HHS's published 200% monthly column, which is
    round_half_up(annual * 2 / 12) — exact at all ten sizes (sizes 9-10 extend
    the annual figure by additional_member_annual_cents first)."""
    fns = load_table("fns").values["gross_limit_200pct_cents"]
    fpl = load_table("fpl").values
    annual = fpl["annual_cents_by_household_size"]
    for size in range(1, 11):
        a = annual[size] if size <= 8 else (
            annual[8] + fpl["additional_member_annual_cents"] * (size - 8)
        )
        expected = int(
            (Decimal(a) * 2 / Decimal(12)).to_integral_value(rounding=ROUND_HALF_UP)
        )
        assert fns[size] == expected, f"size {size}: {fns[size]} != {expected}"


def test_fns_sizes_nine_and_ten_use_published_increments() -> None:
    """Sizes 9-10 are extended from the printed size-8 figures using USDA's
    published each-additional increments: net +$459/member, allotment +$218/person."""
    v = load_table("fns").values
    net = v["net_limit_100pct_cents"]
    allot = v["max_allotment_cents"]
    for size in (9, 10):
        assert net[size] == net[size - 1] + 45900, f"net size {size}"
        assert allot[size] == allot[size - 1] + 21800, f"allotment size {size}"


def test_fns_standard_deduction_present() -> None:
    sd = load_table("fns").values["standard_deduction_cents"]
    assert isinstance(sd, _Mapping) and sd


# ---------------------------------------------------------------------------
# Medicaid table
# ---------------------------------------------------------------------------

MEDICAID_REQUIRED_KEYS = {
    "adult_expansion_pct",
    "pregnant_pct",
    "child_pct_by_age_band",
    "parent_caretaker_pct",
    "magi_disregard_pct",
}


def test_medicaid_has_all_required_keys() -> None:
    v = load_table("medicaid").values
    assert MEDICAID_REQUIRED_KEYS <= set(v)


def test_medicaid_expansion_and_disregard() -> None:
    v = load_table("medicaid").values
    # Base percentage; the 5% MAGI disregard is added at screening (133+5=138%).
    assert v["adult_expansion_pct"] == 133
    assert v["magi_disregard_pct"] == 5


def test_medicaid_percentages_are_positive() -> None:
    v = load_table("medicaid").values
    assert v["pregnant_pct"] > 0
    assert v["parent_caretaker_pct"] > 0
    bands = v["child_pct_by_age_band"]
    assert isinstance(bands, _Mapping) and bands
    for label, pct in bands.items():
        assert isinstance(label, str)
        assert isinstance(pct, (int, float)) and pct > 0


# ---------------------------------------------------------------------------
# All files parse / shared schema fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["fpl", "fns", "medicaid"])
def test_every_file_parses_with_schema_fields(name: str) -> None:
    t = load_table(name)
    assert t.source_url and t.source_name
    assert t.effective_from and t.effective_to
    assert t.values


# ---------------------------------------------------------------------------
# Fix 1: frozen / immutable cached values
# ---------------------------------------------------------------------------


def test_cached_values_top_level_mutation_raises() -> None:
    """Top-level assignment into Table.values must raise TypeError."""
    t = load_table("fns")
    with pytest.raises(TypeError):
        t.values["new_key"] = 999  # type: ignore[index]


def test_cached_values_nested_dict_mutation_raises() -> None:
    """Mutation inside a nested mapping must also raise TypeError."""
    t = load_table("fns")
    with pytest.raises(TypeError):
        t.values["gross_limit_200pct_cents"][1] = 0  # type: ignore[index]


def test_values_is_mapping_proxy() -> None:
    """Table.values should be a MappingProxyType (not a plain dict)."""
    t = load_table("fns")
    assert isinstance(t.values, types.MappingProxyType)


# ---------------------------------------------------------------------------
# Fix 2: date-order guard at load time
# ---------------------------------------------------------------------------


def _write_bad_table(tmp_path: "pytest.TempPathFactory", *, from_: str, to: str) -> str:
    """Write a minimal YAML table with the given date range and return its stem."""
    content = textwrap.dedent(f"""\
        source_url: "https://example.com"
        source_name: "Test table"
        effective_from: "{from_}"
        effective_to: "{to}"
        values:
          foo: 1
    """)
    p = tmp_path / "bad_dates.yaml"
    p.write_text(content, encoding="utf-8")
    return "bad_dates"


def test_date_order_guard_equal_dates(tmp_path: "pytest.TempPathFactory", monkeypatch: pytest.MonkeyPatch) -> None:
    """effective_from == effective_to must raise ValueError at load time."""
    import rules.tables.loader as loader_mod

    stem = _write_bad_table(tmp_path, from_="2026-01-01", to="2026-01-01")
    monkeypatch.setattr(loader_mod, "_TABLES_DIR", tmp_path)
    loader_mod.load_table.cache_clear()
    try:
        with pytest.raises(ValueError, match="bad_dates"):
            loader_mod.load_table(stem)
    finally:
        loader_mod.load_table.cache_clear()


def test_date_order_guard_inverted_dates(tmp_path: "pytest.TempPathFactory", monkeypatch: pytest.MonkeyPatch) -> None:
    """effective_from > effective_to must raise ValueError at load time."""
    import rules.tables.loader as loader_mod

    stem = _write_bad_table(tmp_path, from_="2026-06-01", to="2025-01-01")
    monkeypatch.setattr(loader_mod, "_TABLES_DIR", tmp_path)
    loader_mod.load_table.cache_clear()
    try:
        with pytest.raises(ValueError, match="bad_dates"):
            loader_mod.load_table(stem)
    finally:
        loader_mod.load_table.cache_clear()


# ---------------------------------------------------------------------------
# Fix 5: standard_deduction band keys are strings
# ---------------------------------------------------------------------------


def test_standard_deduction_band_keys_are_strings() -> None:
    """Band keys must be strings; consumers resolve int size → band label."""
    sd = load_table("fns").values["standard_deduction_cents"]
    assert set(sd.keys()) == {"1-2", "3", "4", "5", "6+"}


def test_standard_utility_allowance_band_keys_are_strings() -> None:
    """SUA band keys must also be strings."""
    sua = load_table("fns").values["standard_utility_allowance_cents"]
    assert set(sua.keys()) == {"1", "2", "3", "4", "5+"}
