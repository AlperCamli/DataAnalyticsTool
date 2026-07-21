"""Journey scoring R4-R6 on fixture records (benchmark.scoring, deliverable 4)."""

import pytest

from benchmark.fqn import SnapshotInventory
from benchmark.journey import Draft, ExecutionOutcome, JourneyRecord
from benchmark.scoring import LegResult, score_journey
from benchmark.suite import load_suite
from benchmark.validate import DEFAULT_SNAPSHOTS, DEFAULT_SUITE, load_snapshots


@pytest.fixture(scope="module")
def inventory() -> SnapshotInventory:
    return SnapshotInventory(load_snapshots(DEFAULT_SNAPSHOTS))


@pytest.fixture(scope="module")
def suite():
    return load_suite(DEFAULT_SUITE)


def _draft(seq, system, request, *, ok=True, columns=None, rows=None, final=True, complete=True):
    outcome = ExecutionOutcome(
        ok=ok,
        error=None if ok else "execution failed: relation does not exist",
        row_count=len(rows) if rows is not None else None,
        columns=columns or [],
        rows=rows or [],
    )
    return Draft(seq=seq, system=system, request=request, complete=complete,
                 final=final, executed=True, outcome=outcome)


def _record(case_id, drafts, *, declared=None, condition="machine-kb", rep=0):
    return JourneyRecord(
        case_id=case_id, condition=condition, rep=rep, model_id="test-model",
        drafts=drafts, declared_objects=declared or [],
    )


# -- perfect case (RB-01, byte-stable) -------------------------------------

def test_perfect_byte_stable_case(inventory, suite):
    case = suite.case("RB-01")
    cols, rows = ["signup_day", "new_users"], [["2026-06-01", 9], ["2026-06-02", 5]]
    rec = _record("RB-01", [_draft(1, "supabase", case.golden[0].request, columns=cols, rows=rows)],
                  declared=["supabase.public.users"])
    scored = score_journey(rec, case, inventory, {"supabase": LegResult(cols, rows)})

    assert scored.selection.precision == 1.0 and scored.selection.recall == 1.0
    assert scored.selection.scored == ["supabase.public.users"]
    assert scored.executable.first_try_executable
    assert scored.correctness.correct and scored.correctness.mode == "checksum"


# -- wrong-table case ------------------------------------------------------

def test_wrong_table_case(inventory, suite):
    case = suite.case("RB-01")
    # Agent counts the wrong table entirely.
    wrong = {"dialect": "sql", "statement": "SELECT count(*) FROM public.subscriptions;"}
    cols, rows = ["count"], [[42]]
    golden_cols, golden_rows = ["signup_day", "new_users"], [["2026-06-01", 9]]
    rec = _record("RB-01", [_draft(1, "supabase", wrong, columns=cols, rows=rows)])
    scored = score_journey(rec, case, inventory, {"supabase": LegResult(golden_cols, golden_rows)})

    assert scored.selection.recall == 0.0
    assert scored.selection.precision == 0.0
    assert scored.selection.false_positives == ["supabase.public.subscriptions"]
    assert scored.selection.false_negatives == ["supabase.public.users"]
    assert not scored.correctness.correct  # data does not match golden


# -- unexecutable case -----------------------------------------------------

def test_unexecutable_case(inventory, suite):
    case = suite.case("RB-01")
    broken = {"dialect": "sql", "statement": "SELECT * FROM public.uzers;"}  # typo table
    failed = _draft(1, "supabase", broken, ok=False, final=False)
    rec = _record("RB-01", [failed])
    scored = score_journey(rec, case, inventory, {"supabase": LegResult(["c"], [[1]])})

    assert not scored.executable.first_try_executable
    assert scored.executable.executed and scored.executable.error
    assert scored.selection.precision is None  # nothing executed to score
    assert scored.selection.recall == 0.0
    assert not scored.correctness.correct  # agent produced no result


# -- unstable-case path (RB-02, structural) --------------------------------

def test_unstable_structural_match(inventory, suite):
    case = suite.case("RB-02")
    assert not suite.is_byte_stable("RB-02")
    cols = ["plan_code", "status", "subscribers"]
    golden = [["pro", "active", 10], ["free", "trialing", 3]]
    agent = list(reversed(golden))  # same data, different order
    rec = _record("RB-02", [_draft(1, "supabase", case.golden[0].request, columns=cols, rows=agent)])
    scored = score_journey(rec, case, inventory, {"supabase": LegResult(cols, golden)})

    assert scored.correctness.mode == "structural"
    assert scored.correctness.correct
    assert scored.selection.precision == 1.0 and scored.selection.recall == 1.0


def test_unstable_integer_drift_flagged(inventory, suite):
    case = suite.case("RB-02")
    cols = ["plan_code", "status", "subscribers"]
    golden = [["pro", "active", 10]]
    agent = [["pro", "active", 11]]  # count moved between same-run executions
    rec = _record("RB-02", [_draft(1, "supabase", case.golden[0].request, columns=cols, rows=agent)])
    scored = score_journey(rec, case, inventory, {"supabase": LegResult(cols, golden)})

    leg = scored.correctness.legs[0]
    assert leg.comparison.shape_match and leg.comparison.drift
    assert not scored.correctness.correct


# -- multi-leg case (RB-08, ga4 + supabase) --------------------------------

def test_multi_leg_correctness_and_selection(inventory, suite):
    case = suite.case("RB-08")
    ga4_leg = next(g for g in case.golden if g.system == "ga4")
    sup_leg = next(g for g in case.golden if g.system == "supabase")
    ga4_cols, ga4_rows = ["keyEvents:purchase", "purchaseRevenue"], [[120, 3450.0]]
    sup_cols, sup_rows = ["status", "new_subscriptions"], [["active", 80], ["trialing", 40]]
    rec = _record("RB-08", [
        _draft(1, "ga4", ga4_leg.request, columns=ga4_cols, rows=ga4_rows),
        _draft(2, "supabase", sup_leg.request, columns=sup_cols, rows=sup_rows),
    ])
    golden = {"ga4": LegResult(ga4_cols, ga4_rows), "supabase": LegResult(sup_cols, sup_rows)}
    scored = score_journey(rec, case, inventory, golden)

    assert scored.selection.recall == 1.0 and scored.selection.precision == 1.0
    assert scored.correctness.correct
    assert len(scored.correctness.legs) == 2


# -- declared set is recorded but never scored -----------------------------

def test_declared_set_recorded_not_scored(inventory, suite):
    case = suite.case("RB-01")
    # Agent *claims* it used the right table but actually queried another.
    wrong = {"dialect": "sql", "statement": "SELECT count(*) FROM public.jobs;"}
    rec = _record("RB-01", [_draft(1, "supabase", wrong, columns=["c"], rows=[[1]])],
                  declared=["supabase.public.users"])  # misreported
    scored = score_journey(rec, case, inventory, {"supabase": LegResult(["c"], [[2]])})
    assert scored.selection.declared == ["supabase.public.users"]
    assert scored.selection.scored == ["supabase.public.jobs"]  # parsed statement wins
    assert scored.selection.recall == 0.0


# -- RB-05 GSC contract-metric precision caveat (documented) ---------------

def test_rb05_golden_replica_precision_below_one(inventory, suite):
    """A golden-faithful agent still scores precision < 1 on RB-05: GSC
    returns 4 metrics by contract and the GA4 leg pulls activeUsers, but
    expected_objects lists a curated subset. Recorded as the measurement
    caveat for the report / suite-format proposal."""
    case = suite.case("RB-05")
    drafts = [_draft(i + 1, g.system, g.request, columns=["x"], rows=[[1]])
              for i, g in enumerate(case.golden)]
    rec = _record("RB-05", drafts)
    scored = score_journey(rec, case, inventory, None)
    assert scored.selection.recall == 1.0        # every expected object is pulled
    assert scored.selection.precision < 1.0      # plus contract/extra objects
    # The extras are exactly the contract metrics + the golden's activeUsers.
    assert "ga4.standard.activeUsers" in scored.selection.false_positives
    assert "gsc.standard.impressions" in scored.selection.false_positives
    assert scored.correctness.scored is False    # no golden supplied here
