"""Suite validation: schema, resolution, checksum reproduction (deliverable 1)."""

import copy

import pytest

from benchmark import canonical
from benchmark.fqn import SnapshotInventory
from benchmark.suite import Case, load_suite, suite_from_mapping
from benchmark.validate import (
    ValidationReport,
    _reproduce_checksum,
    load_snapshots,
    validate_schema,
    validate_suite,
)
from tests.conftest import BENCH_SNAPSHOTS, BENCH_SUITE


@pytest.fixture(scope="module")
def inventory() -> SnapshotInventory:
    return SnapshotInventory(load_snapshots(BENCH_SNAPSHOTS))


@pytest.fixture(scope="module")
def raw():
    return load_suite(BENCH_SUITE).raw


def test_real_suite_validates_clean(inventory):
    suite = load_suite(BENCH_SUITE)
    report = validate_suite(suite, inventory)
    assert report.ok, [f.message for f in report.errors]
    # Execution-deferred: every case reports checksum-deferred, no reproduction.
    assert all(
        any(f.kind == "checksum-deferred" and f.case_id == c.id for f in report.findings)
        for c in suite.cases
    )


def test_schema_rejects_bad_case_id(raw):
    bad = copy.deepcopy(raw)
    bad["cases"][0]["id"] = "case1"  # violates ^RB-[0-9]{2}$
    report = ValidationReport()
    validate_schema(bad, report)
    assert any(f.kind == "schema" for f in report.errors)


def test_schema_rejects_missing_required_field(raw):
    bad = copy.deepcopy(raw)
    del bad["cases"][0]["expected_objects"]
    report = ValidationReport()
    validate_schema(bad, report)
    assert any("expected_objects" in f.message for f in report.errors)


def test_schema_rejects_unknown_visual_kind(raw):
    bad = copy.deepcopy(raw)
    bad["cases"][0]["visual_kind"] = "sankey"  # not a registry kind, not other:*
    report = ValidationReport()
    validate_schema(bad, report)
    assert any(f.kind == "schema" for f in report.errors)


def test_schema_accepts_other_prefixed_visual_kind(raw):
    ok = copy.deepcopy(raw)
    ok["cases"][0]["visual_kind"] = "other:sankey"
    report = ValidationReport()
    validate_schema(ok, report)
    assert not report.errors


def test_unresolvable_expected_object_is_error(raw, inventory):
    bad = copy.deepcopy(raw)
    bad["cases"][0]["expected_objects"] = ["supabase.public.ghost_table"]
    report = validate_suite(suite_from_mapping(bad), inventory)
    assert any(f.kind == "expected-object" and f.case_id == "RB-01" for f in report.errors)


def test_golden_leg_system_outside_declared_systems_is_error(raw, inventory):
    bad = copy.deepcopy(raw)
    bad["cases"][0]["golden"][0]["system"] = "ga4"  # RB-01 declares [supabase]
    report = validate_suite(suite_from_mapping(bad), inventory)
    assert any(f.kind == "golden-system" and f.case_id == "RB-01" for f in report.errors)


def test_duplicate_case_id_is_error(raw, inventory):
    bad = copy.deepcopy(raw)
    bad["cases"][1]["id"] = bad["cases"][0]["id"]
    report = validate_suite(suite_from_mapping(bad), inventory)
    assert any(f.kind == "duplicate-id" for f in report.errors)


def _executed_case(rows, checksum) -> Case:
    return Case(
        id="RB-99", request="x", systems=("supabase",), expected_objects=("supabase.public.users",),
        visual_kind="line", recurring=True, golden=(), window={}, blend=None,
        verified_result={"status": "verified", "rows": rows, "checksum": checksum},
        resolution_notes="", notes="", origin="", verified_by="",
    )


def test_checksum_reproduction_matches_executed_rows():
    rows = [{"signup_day": "2026-06-01", "new_users": 9}, {"signup_day": "2026-06-02", "new_users": 5}]
    good = canonical.csv_checksum(["signup_day", "new_users"], [[r["signup_day"], r["new_users"]] for r in rows])
    report = ValidationReport()
    _reproduce_checksum(_executed_case(rows, good), report)
    assert any(f.kind == "checksum" and "reproduced" in f.message for f in report.findings)
    assert not report.errors


def test_checksum_reproduction_detects_tamper():
    rows = [{"signup_day": "2026-06-01", "new_users": 9}]
    report = ValidationReport()
    _reproduce_checksum(_executed_case(rows, "sha256:deadbeef"), report)
    assert any(f.kind == "checksum" and f.level == "error" for f in report.findings)
