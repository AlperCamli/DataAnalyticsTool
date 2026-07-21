"""Benchmark driver invariants (CP-5 deliverable 4).

The driver is thin on purpose, so these tests guard the few things it can
still get wrong — and every one of them would corrupt a baseline silently
rather than loudly:

* a run grid that is not cases x conditions x reps
* `--smoke` running more than one journey
* a fabricated record standing in for a journey that never happened
* records written where the CP-2 harness will not find them
* cost influencing anything (D-77)
"""

from __future__ import annotations

import json

import pytest

from tools.benchmark_driver import (
    ConditionEndpoint,
    JourneySpec,
    extract_result,
    parse_conditions,
    plan_journeys,
    record_path,
    run_journey,
)

CONDITIONS = [
    ConditionEndpoint("enriched-kb", "http://localhost:8100"),
    ConditionEndpoint("machine-kb", "http://localhost:8101"),
    ConditionEndpoint("no-kb", "http://localhost:8102"),
]
CASES = [f"RB-{i:02d}" for i in range(1, 11)]


class TestPlanning:
    def test_full_grid_is_cases_x_conditions_x_reps(self):
        journeys = plan_journeys(CASES, CONDITIONS, reps=1, smoke=False)
        assert len(journeys) == 30  # the CP-5 exit criterion's 30+
        assert len({(j.case_id, j.condition, j.rep) for j in journeys}) == 30

    def test_every_case_runs_on_every_condition(self):
        # R2: no case may be scored on a subset of conditions, or the
        # comparison is between different case mixes.
        journeys = plan_journeys(CASES, CONDITIONS, reps=1, smoke=False)
        for case_id in CASES:
            got = {j.condition for j in journeys if j.case_id == case_id}
            assert got == {c.name for c in CONDITIONS}

    def test_reps_multiply_the_grid(self):
        assert len(plan_journeys(CASES, CONDITIONS, reps=3, smoke=False)) == 90

    def test_smoke_is_exactly_one_journey(self):
        # D-76.3d: the smoke run is authorized separately from the batch.
        journeys = plan_journeys(CASES, CONDITIONS, reps=5, smoke=True)
        assert journeys == [JourneySpec("RB-01", "enriched-kb", 1)]


class TestConditionParsing:
    def test_parses_name_url_pairs(self):
        got = parse_conditions(["no-kb=http://localhost:8102"])
        assert got == [ConditionEndpoint("no-kb", "http://localhost:8102")]

    def test_url_containing_equals_survives(self):
        got = parse_conditions(["no-kb=http://h/mcp?profile=nokb"])
        assert got[0].url == "http://h/mcp?profile=nokb"

    def test_malformed_spec_raises(self):
        with pytest.raises(ValueError):
            parse_conditions(["no-kb"])


class TestRecordPlacement:
    def test_path_is_condition_scoped_so_the_harness_ingests_it(self, tmp_path):
        p = record_path(tmp_path, JourneySpec("RB-03", "machine-kb", 2))
        assert p == tmp_path / "machine-kb" / "RB-03-rep2.json"

    def test_reps_do_not_collide(self, tmp_path):
        a = record_path(tmp_path, JourneySpec("RB-01", "no-kb", 1))
        b = record_path(tmp_path, JourneySpec("RB-01", "no-kb", 2))
        assert a != b


class TestResultExtraction:
    def test_reads_the_terminal_result_event(self):
        stream = "\n".join([
            json.dumps({"type": "assistant", "message": {}}),
            json.dumps({"type": "result", "session_id": "s-1", "total_cost_usd": 0.12,
                        "usage": {"input_tokens": 10}}),
        ])
        got = extract_result(stream)
        assert got["session_id"] == "s-1"
        assert got["cost_usd"] == 0.12
        assert got["tokens"] == {"input_tokens": 10}

    def test_absent_cost_stays_absent(self):
        # D-77.3: "unknown" and "free" are different facts.
        stream = json.dumps({"type": "result", "session_id": "s-2"})
        got = extract_result(stream)
        assert "cost_usd" not in got

    def test_tolerates_non_json_lines(self):
        stream = "not json\n" + json.dumps({"type": "result", "session_id": "s-3"})
        assert extract_result(stream)["session_id"] == "s-3"


class TestRunJourney:
    def test_dry_run_invokes_nothing(self, tmp_path):
        ok, detail = run_journey(
            JourneySpec("RB-01", "no-kb", 1), CONDITIONS[2], "m", "prompt",
            tmp_path, tmp_path, 60, dry_run=True,
        )
        assert ok is True
        assert "[dry-run]" in detail
        assert not (tmp_path / "no-kb" / "RB-01-rep1.json").exists()

    def test_missing_claude_binary_fails_loudly(self, tmp_path, monkeypatch):
        import tools.benchmark_driver as drv

        def boom(*a, **k):
            raise FileNotFoundError

        monkeypatch.setattr(drv.subprocess, "run", boom)
        ok, detail = run_journey(
            JourneySpec("RB-01", "no-kb", 1), CONDITIONS[2], "m", "p",
            tmp_path, tmp_path, 60, dry_run=False,
        )
        assert ok is False
        assert "not on PATH" in detail

    def test_a_journey_that_emitted_no_record_is_a_failure_not_a_fabrication(
        self, tmp_path, monkeypatch
    ):
        """The driver must never synthesize a record.

        A fabricated record would be ingested and scored as though a real
        journey had happened — the single worst thing this driver could do,
        because the resulting number looks exactly like a real one.
        """
        import tools.benchmark_driver as drv

        class Proc:
            returncode = 0
            stdout = json.dumps({"type": "result", "session_id": "s"})
            stderr = ""

        monkeypatch.setattr(drv.subprocess, "run", lambda *a, **k: Proc())
        ok, detail = run_journey(
            JourneySpec("RB-01", "no-kb", 1), CONDITIONS[2], "m", "p",
            tmp_path, tmp_path, 60, dry_run=False,
        )
        assert ok is False
        assert "emitted no record" in detail
        assert not (tmp_path / "no-kb" / "RB-01-rep1.json").exists()

    def test_driver_metadata_never_overwrites_what_the_skill_recorded(
        self, tmp_path, monkeypatch
    ):
        import tools.benchmark_driver as drv

        dest = tmp_path / "no-kb" / "RB-01-rep1.json"
        dest.parent.mkdir(parents=True)
        dest.write_text(json.dumps({
            "case_id": "RB-01", "condition": "no-kb", "rep": 1,
            "model_id": "the-skill-said-this", "drafts": [],
        }))

        class Proc:
            returncode = 0
            stdout = json.dumps({"type": "result", "session_id": "s", "total_cost_usd": 0.5})
            stderr = ""

        monkeypatch.setattr(drv.subprocess, "run", lambda *a, **k: Proc())
        ok, _ = run_journey(
            JourneySpec("RB-01", "no-kb", 1), CONDITIONS[2], "other-model", "p",
            tmp_path, tmp_path, 60, dry_run=False,
        )

        assert ok is True
        record = json.loads(dest.read_text())
        # setdefault, not assignment: the skill's own record wins.
        assert record["model_id"] == "the-skill-said-this"
        assert record["cost_usd"] == 0.5
