"""Canonical CSV, checksum, and R5 comparison (benchmark.canonical)."""

import datetime as dt
from decimal import Decimal

import pytest

from benchmark import canonical


def test_canonical_csv_sorts_data_rows_not_header():
    text = canonical.canonical_csv(
        ["day", "n"],
        [["2026-06-02", 5], ["2026-06-01", 9], ["2026-06-03", 1]],
    )
    lines = text.splitlines()
    assert lines[0] == "day,n"  # header stays first
    assert lines[1:] == ["2026-06-01,9", "2026-06-02,5", "2026-06-03,1"]  # sorted
    assert text.endswith("\n")


def test_canonical_csv_is_order_independent_for_checksum():
    a = canonical.csv_checksum(["k", "v"], [["b", 2], ["a", 1]])
    b = canonical.csv_checksum(["k", "v"], [["a", 1], ["b", 2]])
    assert a == b  # row order does not change the checksum
    assert a.startswith("sha256:")


def test_canonical_csv_escapes_and_renders_types():
    text = canonical.canonical_csv(
        ["label", "flag", "when", "amt"],
        [["a,b", True, dt.date(2026, 6, 1), None]],
    )
    assert text.splitlines()[1] == '"a,b",true,2026-06-01,'


def test_checksum_changes_with_data():
    base = canonical.csv_checksum(["n"], [[1]])
    assert base != canonical.csv_checksum(["n"], [[2]])
    assert base != canonical.csv_checksum(["m"], [[1]])  # header participates


def test_values_equal_integer_exact_float_relative():
    assert canonical.values_equal(5, 5)
    assert not canonical.values_equal(5, 6)  # integers exact
    assert canonical.values_equal(1.0, 1.0 + 1e-12)  # floats within 1e-9 rel
    assert not canonical.values_equal(1.0, 1.0 + 1e-3)
    assert canonical.values_equal(Decimal("12.3"), 12.3)
    assert canonical.values_equal(None, None)
    assert not canonical.values_equal(None, 0)


def test_compare_byte_stable_checksum_match():
    cols = ["signup_day", "new_users"]
    rows = [["2026-06-01", 9], ["2026-06-02", 5]]
    cmp = canonical.compare_results(
        byte_stable=True,
        golden_columns=cols, golden_rows=rows,
        agent_columns=cols, agent_rows=list(reversed(rows)),
    )
    assert cmp.correct and cmp.checksum_match and cmp.mode == "checksum"


def test_compare_byte_stable_data_correct_but_alias_differs():
    cmp = canonical.compare_results(
        byte_stable=True,
        golden_columns=["signup_day", "new_users"], golden_rows=[["2026-06-01", 9]],
        agent_columns=["day", "count"], agent_rows=[["2026-06-01", 9]],
    )
    assert not cmp.correct  # strict packet checksum includes the header
    assert not cmp.checksum_match
    assert cmp.values_match  # but the data is right — recorded as such
    assert cmp.notes


def test_compare_structural_shape_and_values():
    cmp = canonical.compare_results(
        byte_stable=False,
        golden_columns=["plan", "status", "n"],
        golden_rows=[["pro", "active", 10], ["free", "trialing", 3]],
        agent_columns=["plan", "status", "n"],
        agent_rows=[["free", "trialing", 3], ["pro", "active", 10]],
    )
    assert cmp.correct and cmp.shape_match and cmp.values_match and cmp.mode == "structural"


def test_compare_structural_integer_drift_flagged_not_fatal_shape():
    # Same shape, one integer count differs (live mutation between execs).
    cmp = canonical.compare_results(
        byte_stable=False,
        golden_columns=["status", "n"], golden_rows=[["active", 100]],
        agent_columns=["status", "n"], agent_rows=[["active", 101]],
    )
    assert cmp.shape_match
    assert not cmp.values_match
    assert cmp.drift  # only-integer disagreement => drift signature
    assert not cmp.correct  # still not correct, but drift is the explanation
    assert cmp.notes


def test_compare_structural_shape_mismatch():
    cmp = canonical.compare_results(
        byte_stable=False,
        golden_columns=["a"], golden_rows=[[1], [2]],
        agent_columns=["a"], agent_rows=[[1]],
    )
    assert not cmp.shape_match and not cmp.correct and not cmp.drift
