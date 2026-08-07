"""Snapshot inventory, resolution, and scored-set extraction (benchmark.fqn)."""

import json

import pytest

from benchmark.fqn import SnapshotInventory, object_fqn
from benchmark.suite import load_suite
from tests.conftest import BENCH_SNAPSHOTS, BENCH_SUITE


@pytest.fixture(scope="module")
def inventory() -> SnapshotInventory:
    snaps = [json.loads(p.read_text(encoding="utf-8")) for p in BENCH_SNAPSHOTS]
    return SnapshotInventory(snaps)


@pytest.fixture(scope="module")
def suite():
    return load_suite(BENCH_SUITE)


def test_expected_objects_resolve_across_systems(inventory):
    for fqn in [
        "supabase.public.users",
        "supabase.public.job_status_history",
        "gsc.standard.query",
        "gsc.standard.clicks",
        "ga4.standard.country",
        "ga4.standard.keyEvents:purchase",  # colon in name, never mis-split
        "ga4.standard.purchaseRevenue",
    ]:
        assert inventory.resolves(fqn), fqn


def test_fabricated_object_does_not_resolve(inventory):
    assert not inventory.resolves("supabase.public.nonexistent")
    assert not inventory.resolves("ga4.standard.madeUpMetric")
    assert inventory.unresolved(
        ["supabase.public.users", "supabase.public.ghost"]
    ) == ["supabase.public.ghost"]


def test_every_seed_expected_object_resolves(inventory, suite):
    for case in suite.cases:
        assert inventory.unresolved(case.expected_objects) == [], case.id


def test_sql_extraction_single_table(inventory, suite):
    leg = suite.case("RB-01").golden[0]
    got = inventory.extract("supabase", leg.request)
    assert got.parse_ok
    assert got.fqns == {"supabase.public.users"}


def test_sql_extraction_excludes_cte_and_finds_all_base_tables(inventory, suite):
    # RB-07 has a `cohort` CTE plus five base tables (multi-statement w/ SET).
    leg = suite.case("RB-07").golden[0]
    got = inventory.extract("supabase", leg.request)
    assert got.parse_ok
    assert got.fqns == {
        "supabase.public.users",
        "supabase.public.master_cvs",
        "supabase.public.tailored_cvs",
        "supabase.public.exports",
        "supabase.public.subscriptions",
    }


def test_sql_extraction_unqualified_name_binds_to_unique_schema(inventory):
    got = inventory.extract("supabase", {"dialect": "sql", "statement": "SELECT * FROM users;"})
    assert got.fqns == {"supabase.public.users"}


def test_sql_set_only_statement_has_no_relations(inventory):
    got = inventory.extract("supabase", {"dialect": "sql", "statement": "SET statement_timeout='30s';"})
    assert got.parse_ok and got.fqns == set()


def test_sql_unparseable_flags_not_ok(inventory):
    got = inventory.extract("supabase", {"dialect": "sql", "statement": "SELECT FROM WHERE ("})
    assert not got.parse_ok


def test_gsc_api_extraction_adds_contract_metrics(inventory, suite):
    # RB-03: body names only the `query` dimension; GSC returns 4 metrics.
    leg = suite.case("RB-03").golden[0]
    got = inventory.extract("gsc", leg.request)
    assert got.fqns == {
        "gsc.standard.query",
        "gsc.standard.clicks",
        "gsc.standard.impressions",
        "gsc.standard.ctr",
        "gsc.standard.position",
    }


def test_gsc_empty_dimensions_still_returns_contract_metrics(inventory, suite):
    # RB-05 stage 1: dimensions [] -> property-level totals, 4 metrics only.
    gsc_leg = next(g for g in suite.case("RB-05").golden if g.system == "gsc")
    got = inventory.extract("gsc", gsc_leg.request)
    assert got.fqns == {
        "gsc.standard.clicks",
        "gsc.standard.impressions",
        "gsc.standard.ctr",
        "gsc.standard.position",
    }


def test_ga4_api_extraction_dims_and_metrics(inventory, suite):
    leg = suite.case("RB-04").golden[0]
    got = inventory.extract("ga4", leg.request)
    assert got.fqns == {
        "ga4.standard.country",
        "ga4.standard.userAgeBracket",
        "ga4.standard.userGender",
        "ga4.standard.activeUsers",
        "ga4.standard.newUsers",
    }


def test_ga4_key_event_metric_extracts(inventory, suite):
    ga4_leg = next(g for g in suite.case("RB-08").golden if g.system == "ga4")
    got = inventory.extract("ga4", ga4_leg.request)
    assert "ga4.standard.keyEvents:purchase" in got.fqns
    assert "ga4.standard.purchaseRevenue" in got.fqns
