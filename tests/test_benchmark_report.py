"""Results artifact + report (benchmark.baseline, benchmark.report)."""

import json

import pytest

from benchmark.baseline import build_artifact, journey_artifact
from benchmark.conditions import no_kb_condition
from benchmark.fqn import SnapshotInventory
from benchmark.journey import Draft, ExecutionOutcome, JourneyRecord
from benchmark.report import build_report
from benchmark.scoring import LegResult, score_journey
from benchmark.suite import load_suite
from benchmark.validate import load_snapshots
from tests.conftest import BENCH_SNAPSHOTS, BENCH_SUITE


@pytest.fixture(scope="module")
def suite():
    return load_suite(BENCH_SUITE)


@pytest.fixture(scope="module")
def inventory():
    return SnapshotInventory(load_snapshots(BENCH_SNAPSHOTS))


def _record(case_id, condition, statement, cols, rows):
    o = ExecutionOutcome(ok=True, columns=cols, rows=rows, row_count=len(rows))
    d = Draft(seq=1, system="supabase", request={"dialect": "sql", "statement": statement},
              complete=True, final=True, executed=True, outcome=o)
    return JourneyRecord(case_id=case_id, condition=condition, rep=0, model_id="claude-opus-4-8",
                         backend="claude-code", cost_usd=0.3, drafts=[d],
                         declared_objects=["supabase.public.users"])


def test_journey_artifact_is_sanitized(suite, inventory):
    case = suite.case("RB-01")
    rec = _record("RB-01", "no-kb", "SELECT created_at FROM public.users", ["d", "n"], [["x", 1], ["y", 2]])
    golden = {"supabase": LegResult(["d", "n"], [["x", 1], ["y", 2]])}
    sc = score_journey(rec, case, inventory, golden)
    art = journey_artifact(rec, sc)
    d = art["drafts"][0]
    assert "rows" not in d  # no raw customer values
    assert d["result_checksum"].startswith("sha256:") and d["row_count"] == 2
    assert art["selection"]["recall"] == 1.0
    assert art["correctness"]["scored"] is True


def test_build_artifact_and_report(suite, inventory):
    case = suite.case("RB-01")
    conds = [no_kb_condition()]
    rec = _record("RB-01", "no-kb", "SELECT created_at FROM public.users", ["d", "n"], [["x", 1]])
    golden = {"supabase": LegResult(["d", "n"], [["x", 1]])}
    sc = score_journey(rec, case, inventory, golden)
    artifact = build_artifact(
        run_id="t", kind="smoke", suite=suite, conditions=conds, reps=1,
        model_id="claude-opus-4-8", backend="claude-code",
        snapshot_refs={"supabase": "sha256:abc"}, scored=[(rec, sc)],
        golden_executions=[{"case_id": "RB-01", "system": "supabase"}], ga4_count=0,
        started_at="t0", ended_at="t1")
    # cases_meta present + self-contained
    assert {c["id"] for c in artifact["cases_meta"]} == {c.id for c in suite.cases}
    report = build_report(artifact)
    assert "Three-condition comparison" in report
    assert "MC-1 retrieval recall" in report
    assert "5/5" in report and "other:funnel" in report  # FM-2 coverage
    assert "recurring: true` count: **10**" in report     # SP-4/FM-4


def test_report_handles_none_precision(suite, inventory):
    # A journey that executed nothing to score -> precision None must not crash.
    case = suite.case("RB-01")
    rec = JourneyRecord(case_id="RB-01", condition="no-kb", rep=0, model_id="m", backend="claude-code")
    sc = score_journey(rec, case, inventory, None)
    artifact = build_artifact(
        run_id="t", kind="smoke", suite=suite, conditions=[no_kb_condition()], reps=1,
        model_id="m", backend="claude-code", snapshot_refs={}, scored=[(rec, sc)],
        golden_executions=[], ga4_count=0, started_at="a", ended_at="b")
    report = build_report(artifact)  # must not raise on None precision / unscored correctness
    assert "no-kb" in report
