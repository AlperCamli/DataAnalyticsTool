"""The KB-CI gate (D-116.4): a merge needs a check that demonstrably ran.

Live finding this covers: KB PR #40 opened with no `pull_request` run at
all — the operator closed and reopened it by hand to get one, and the
runs then arrived seventeen minutes late. The absence of a check had
looked exactly like a pass.

Three behaviours, each an exit code:

* a reported, green check → 0, and the run URL is printed as evidence;
* nothing reported inside the grace window → the gate causes a run once
  (close + reopen, which fires `pull_request` without needing `workflow`
  token scope or a change to the CI file) and then passes on it;
* nothing reported at all → **2**, with "DO NOT MERGE" in the output —
  and 2 is deliberately not 1, because "no check ran" and "the check
  failed" are different facts about a diff.

`gh` is stubbed by a script on PATH, so the test exercises the real
subprocess path and the real argument shapes without a network.
"""

import importlib.util
import json
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).resolve().parents[1] / "core" / "skills" / "enrich" / "ci_gate.py"

spec = importlib.util.spec_from_file_location("ci_gate", TOOL_PATH)
ci_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_gate)


PR_VIEW = {
    "number": 40,
    "headRefOid": "029a7cd0ad4e0ea0fd1b2ec65bf6ab31ec20e274",
    "url": "https://github.example/acme/kb/pull/40",
    "state": "OPEN",
    "headRefName": "enrich/subscriptions-plan-code",
}


def _run(name: str, conclusion: str = "success", status: str = "completed") -> dict:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.example/acme/kb/actions/runs/1#{name}",
    }


def stub_gh(tmp_path: Path, *, phases: list[list[dict]]) -> Path:
    """A `gh` that returns the next phase's check-runs on each API call.

    `phases` is consumed one entry per `gh api …/check-runs` call, so a
    test can say "nothing, nothing, then a green run" and see what the
    gate does in between. Every invocation is appended to `calls.log`.
    """
    script = tmp_path / "gh"
    state = tmp_path / "phase"
    state.write_text("0")
    script.write_text(
        f'''#!/usr/bin/env python3
import json, sys
from pathlib import Path

PHASES = json.loads({json.dumps(json.dumps(phases))})
PR_VIEW = json.loads({json.dumps(json.dumps(PR_VIEW))})
state = Path({json.dumps(str(state))})
log = Path({json.dumps(str(tmp_path / "calls.log"))})

args = sys.argv[1:]
with log.open("a") as fh:
    fh.write(" ".join(args) + "\\n")

if args[:2] == ["repo", "view"]:
    print(json.dumps({{"nameWithOwner": "acme/kb"}}))
elif args[:2] == ["pr", "view"]:
    print(json.dumps(PR_VIEW))
elif args[0] == "api":
    i = int(state.read_text())
    runs = PHASES[min(i, len(PHASES) - 1)]
    state.write_text(str(i + 1))
    print(json.dumps({{"total_count": len(runs), "check_runs": runs}}))
elif args[:2] in (["pr", "close"], ["pr", "reopen"]):
    pass
else:
    sys.exit(9)
'''
    )
    script.chmod(0o755)
    return script


def gate(tmp_path, phases, **kw):
    """Run the gate with a stubbed clock so nothing actually sleeps."""
    ticks = {"t": 0.0}

    def now():
        return ticks["t"]

    def sleep(seconds):
        ticks["t"] += seconds

    import io

    out = io.StringIO()
    code = ci_gate.gate(
        "40",
        binary=str(stub_gh(tmp_path, phases=phases)),
        poll=10.0,
        sleep=sleep,
        now=now,
        out=out,
        **kw,
    )
    return code, out.getvalue(), (tmp_path / "calls.log").read_text()


def test_reported_green_check_passes_and_prints_the_evidence(tmp_path):
    code, out, calls = gate(tmp_path, [[_run("KB CI")]])
    assert code == 0
    assert "CHECK REPORTED GREEN" in out
    # The URL is the evidence a runbook records; a bare "green" is not.
    assert "actions/runs/1" in out
    # The check is looked up by head sha, never by branch: a branch moves.
    assert f"commits/{PR_VIEW['headRefOid']}/check-runs" in calls
    # Nothing was closed or reopened — remediation is for the defect case.
    assert "pr close" not in calls


def test_a_failing_check_is_1_not_2(tmp_path):
    code, out, _ = gate(tmp_path, [[_run("KB CI", conclusion="failure")]])
    assert code == 1
    assert "CHECK FAILED" in out


def test_pending_runs_are_waited_out(tmp_path):
    code, out, _ = gate(
        tmp_path,
        [[_run("KB CI", conclusion=None, status="in_progress")], [_run("KB CI")]],
    )
    assert code == 0
    assert "still going" in out


def test_no_run_inside_the_grace_window_is_caused_once_then_passes(tmp_path):
    # The PR #40 shape: nothing at open, then a run once the gate pokes it.
    code, out, calls = gate(
        tmp_path,
        [[], [], [], [_run("KB CI")]],
        grace=20.0,
    )
    assert code == 0
    assert "NO CHECK RUN after" in out
    # It says what it did, and it did it exactly once.
    assert "closing and reopening" in out
    assert calls.count("pr close 40") == 1
    assert calls.count("pr reopen 40") == 1
    assert "CHECK REPORTED GREEN" in out


def test_a_check_that_never_reports_is_2_and_says_do_not_merge(tmp_path):
    code, out, calls = gate(tmp_path, [[]], grace=20.0, timeout=60.0)
    assert code == 2
    assert "DO NOT MERGE" in out
    assert "the absence of a check is not a pass" in out
    # It still tried the remediation before giving up, and says so.
    assert "close/reopen did not produce one" in out
    assert calls.count("pr reopen 40") == 1


def test_gh_failure_is_its_own_exit_code(tmp_path, monkeypatch):
    # Tooling failure is neither evidence that a check ran nor that it
    # did not — conflating it with either is how a gate gets ignored.
    monkeypatch.setenv("PATH", str(tmp_path))
    code = ci_gate.main(["40", "--gh", str(tmp_path / "nonexistent-gh")])
    assert code == 3


def test_the_skill_tells_the_session_to_run_it():
    skill = (TOOL_PATH.parent / "SKILL.md").read_text()
    assert "ci_gate.py" in skill
    # And states the rule, not just the command: the absence of a check is
    # neither a pass nor a defect in the diff, and the skill must say so
    # rather than reporting whichever is convenient.
    assert "no check ever reported" in skill
    assert "must not be merged on this evidence" in skill
