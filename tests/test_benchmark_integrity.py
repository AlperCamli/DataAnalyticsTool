"""CI suite-integrity check + staged defects (benchmark.integrity, R7)."""

import copy
import json

import pytest

from benchmark.fqn import SnapshotInventory
from benchmark.integrity import (
    integrity_report,
    main as integrity_main,
    scan_contamination,
    _sql_column_issues,
)
from benchmark.suite import load_suite
from benchmark.validate import load_snapshots
from tests.conftest import BENCH_SNAPSHOTS, BENCH_SUITE


@pytest.fixture
def snaps():
    return load_snapshots(BENCH_SNAPSHOTS)


@pytest.fixture
def suite():
    return load_suite(BENCH_SUITE)


def _drop_column(snaps, system, table, column):
    out = copy.deepcopy(snaps)
    for s in out:
        if s["system"] == system:
            for o in s["objects"]:
                if o["name"] == table:
                    o["columns"] = [c for c in o["columns"] if c["name"] != column]
    return out


def _drop_object(snaps, system, name):
    out = copy.deepcopy(snaps)
    for s in out:
        if s["system"] == system:
            s["objects"] = [o for o in s["objects"] if o["name"] != name]
    return out


def test_integrity_green_on_current_suite(snaps, suite):
    report = integrity_report(suite, SnapshotInventory(snaps))
    assert report.ok, [f.message for f in report.errors]
    assert not any(f.kind == "golden-column" for f in report.findings)


def test_column_resolver_has_no_false_positives(snaps, suite):
    inv = SnapshotInventory(snaps)
    for case in suite.cases:
        for leg in case.golden:
            if leg.dialect == "sql":
                assert _sql_column_issues(leg.system, leg.request["statement"], inv) == [], case.id


def test_staged_defect_dropped_column_fails_ci(snaps, suite):
    # The exit-criterion defect: a golden references a dropped column.
    inv = SnapshotInventory(_drop_column(snaps, "supabase", "users", "created_at"))
    report = integrity_report(suite, inv)
    assert not report.ok
    col_errs = [f for f in report.errors if f.kind == "golden-column"]
    hit_cases = {f.case_id for f in col_errs}
    assert {"RB-01", "RB-05", "RB-07"} <= hit_cases  # incl. RB-07's CTE reference


def test_staged_defect_dropped_column_deep_in_cte(snaps, suite):
    # RB-07 references master_cvs.is_deleted inside a correlated subquery.
    inv = SnapshotInventory(_drop_column(snaps, "supabase", "master_cvs", "is_deleted"))
    report = integrity_report(suite, inv)
    assert any(
        f.kind == "golden-column" and f.case_id == "RB-07"
        and "master_cvs.is_deleted" in f.message
        for f in report.errors
    )


def test_staged_defect_dropped_table_fails_ci(snaps, suite):
    inv = SnapshotInventory(_drop_object(snaps, "supabase", "subscriptions"))
    report = integrity_report(suite, inv)
    assert not report.ok
    kinds = {(f.kind, f.case_id) for f in report.errors}
    # subscriptions is an expected object of RB-02/RB-10 and a golden ref.
    assert ("expected-object", "RB-02") in kinds
    assert any(f.kind == "golden-object" for f in report.errors)


def test_ga4_dropped_metric_fails_ci(snaps, suite):
    # keyEvents:purchase is RB-08's GA4 metric — drop it, CI must fail.
    inv = SnapshotInventory(_drop_object(snaps, "ga4", "keyEvents:purchase"))
    report = integrity_report(suite, inv)
    assert any(f.case_id == "RB-08" for f in report.errors)


def test_contamination_flag(tmp_path, snaps, suite):
    doc = tmp_path / "systems" / "supabase" / "public" / "users.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "---\n"
        "doc_class: human-object\n"
        "object: supabase.public.users\n"
        "status: contaminated\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    contaminated = scan_contamination(tmp_path)
    assert contaminated == {"supabase.public.users": "systems/supabase/public/users.md"}
    report = integrity_report(suite, SnapshotInventory(snaps), kb_root=tmp_path)
    flags = [f for f in report.warnings if f.kind == "contaminated-context"]
    # RB-01, RB-05, RB-07 all expect supabase.public.users.
    assert {"RB-01", "RB-05", "RB-07"} <= {f.case_id for f in flags}
    assert report.ok  # contamination is a flag, not a CI failure


def test_no_contamination_in_current_kb(snaps, suite):
    from benchmark.integrity import DEFAULT_KB
    if DEFAULT_KB.is_dir():
        assert scan_contamination(DEFAULT_KB) == {}


# --------------------------------------------------------------------------
# The KB-resident suite (D-119.2a): what KB CI actually runs.


def _kb_with_suite(root, suite_text, snaps):
    """A KB tree shaped like KB §3: the suite at its home, the accepted
    snapshots where the goldens resolve against them."""
    bench = root / ".contextlayer" / "benchmark"
    bench.mkdir(parents=True)
    (bench / "suite.yaml").write_text(suite_text, encoding="utf-8")
    snap_dir = root / ".contextlayer" / "snapshots"
    snap_dir.mkdir(parents=True)
    for snap in snaps:
        (snap_dir / f"{snap['system']}.json").write_text(json.dumps(snap), encoding="utf-8")
    return root


def test_kb_root_discovers_suite_and_snapshots(tmp_path, snaps, capsys):
    _kb_with_suite(tmp_path, BENCH_SUITE.read_text(encoding="utf-8"), snaps)
    assert integrity_main(["--kb", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "cvbuilder suite v0" in out and "GREEN" in out


def test_doctored_golden_referencing_a_dropped_column_fails_ci(tmp_path, snaps, capsys):
    """The exit-criterion defect, through the path KB CI takes: a golden
    edited to reference a column the estate does not have."""
    doctored = BENCH_SUITE.read_text(encoding="utf-8").replace(
        "date_trunc('day', created_at AT TIME ZONE 'UTC')",
        "date_trunc('day', signed_up_at AT TIME ZONE 'UTC')")
    assert "signed_up_at" in doctored  # the edit landed
    _kb_with_suite(tmp_path, doctored, snaps)
    assert integrity_main(["--kb", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "supabase.public.users.signed_up_at referenced but not in snapshot" in out
    assert "FAILED" in out


def test_kb_without_a_suite_passes_and_says_so(tmp_path, snaps, capsys):
    """Playbook step 8 not reached yet is a stage of onboarding, not a
    defect — but it must never look like a suite that was checked."""
    snap_dir = tmp_path / ".contextlayer" / "snapshots"
    snap_dir.mkdir(parents=True)
    for snap in snaps:
        (snap_dir / f"{snap['system']}.json").write_text(json.dumps(snap), encoding="utf-8")
    assert integrity_main(["--kb", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no golden suite" in out and ".contextlayer/benchmark/suite.yaml" in out


def test_suite_present_but_no_accepted_snapshots_is_an_error(tmp_path, capsys):
    bench = tmp_path / ".contextlayer" / "benchmark"
    bench.mkdir(parents=True)
    (bench / "suite.yaml").write_text(BENCH_SUITE.read_text(encoding="utf-8"), encoding="utf-8")
    assert integrity_main(["--kb", str(tmp_path)]) == 1
    assert "no accepted snapshots" in capsys.readouterr().out


def test_contamination_flag_does_not_fail_the_kb_run(tmp_path, snaps, capsys):
    """A contaminated doc under a golden is surfaced, never blocking — the
    repair pressure belongs in triage, not in a red CI on somebody else's
    pull request."""
    _kb_with_suite(tmp_path, BENCH_SUITE.read_text(encoding="utf-8"), snaps)
    doc = tmp_path / "systems" / "supabase" / "public" / "users.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "---\ndoc_class: human-object\nobject: supabase.public.users\n"
        "status: contaminated\n---\n\nbody\n", encoding="utf-8")
    assert integrity_main(["--kb", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "contaminated-context" in out and "GREEN" in out
