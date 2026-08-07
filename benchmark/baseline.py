"""Deliverable 6 — baseline orchestrator + R8 results artifact.

Runs the suite as cases × conditions × reps through one backend (R9),
executing each golden leg once per run (``GoldenCache``) for R5 correctness,
scoring every journey (R4-R6), and persisting a versioned JSON artifact
(R8) keyed by {suite_version, journey-prompt version, kb_refs, snapshot_refs,
condition, model id, backend, timestamp}. Per-journey checkpointing lets a
held/interrupted run resume.

The committed artifact is **sanitized**: it stores each result's columns,
row count, and a canonical-CSV checksum — never the raw customer values.
Full rows live only in the per-journey scratch checkpoints (git-ignored).
The artifact schema is the Ops-Postgres import contract.

CLI (launch the full run later):
    python -m benchmark.baseline --backend claude-code --reps 3 \\
        --out results/ --workdir <scratch> --enriched-kb ~/Desktop/kb
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmark import canonical
from benchmark.conditions import (
    ENRICHED_KB, MACHINE_KB, NO_KB, Condition,
    enriched_kb_condition, no_kb_condition,
)
from benchmark.fqn import SnapshotInventory
from benchmark.journey import JourneyRecord
from benchmark.runner import JOURNEY_PROMPT_VERSION
from benchmark.scoring import ScoredJourney, score_journey
from benchmark.suite import Case, Suite

ARTIFACT_SCHEMA_VERSION = "1"
R6_NOTE = ("R6 executable = first-try execution success; refines to "
           "validate-pass when validate_sql lands (CP-4).")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _snapshot_refs(snapshots: Sequence[Mapping[str, Any]], snap_dir: Path) -> dict[str, str]:
    refs = {}
    for snap in snapshots:
        p = snap_dir / f"{snap['system']}.json"
        if p.is_file():
            refs[snap["system"]] = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    return refs


def _draft_artifact(draft) -> dict:
    o = draft.outcome
    checksum = canonical.csv_checksum(o.columns, o.rows) if o and o.ok and o.columns else None
    return {
        "seq": draft.seq, "system": draft.system, "request": draft.request,
        "final": draft.final, "executed": draft.executed,
        "ok": bool(o and o.ok), "error": o.error if o else None,
        "columns": o.columns if o else [], "row_count": o.row_count if o else 0,
        "result_checksum": checksum,  # fingerprint, not the values
    }


def _correctness_artifact(sc) -> dict:
    legs = []
    for leg in sc.correctness.legs:
        c = leg.comparison
        legs.append({
            "system": leg.system, "scored": leg.scored, "correct": leg.correct,
            "reason": leg.reason,
            "checksum_match": c.checksum_match if c else None,
            "values_match": c.values_match if c else None,
            "shape_match": c.shape_match if c else None,
            "golden_shape": list(c.golden_shape) if c else None,
            "agent_shape": list(c.agent_shape) if c else None,
            "drift": c.drift if c else None,
            "notes": list(c.notes) if c else [],
        })
    return {"scored": sc.correctness.scored, "correct": sc.correctness.correct,
            "mode": sc.correctness.mode, "reason": sc.correctness.reason, "legs": legs}


def journey_artifact(record: JourneyRecord, sc: ScoredJourney) -> dict:
    return {
        "case_id": record.case_id, "condition": record.condition, "rep": record.rep,
        "backend": record.backend, "model_id": record.model_id,
        "cost_usd": record.cost_usd, "session_id": record.session_id,
        "tokens": record.tokens, "tool_calls": record.tool_calls,
        "started_at": record.started_at, "ended_at": record.ended_at,
        "context_reads": record.context_reads, "declared_objects": record.declared_objects,
        "drafts": [_draft_artifact(d) for d in record.drafts],
        "selection": {
            "precision": sc.selection.precision, "recall": sc.selection.recall,
            "expected": sc.selection.expected, "scored": sc.selection.scored,
            "true_positives": sc.selection.true_positives,
            "false_positives": sc.selection.false_positives,
            "false_negatives": sc.selection.false_negatives,
            "declared": sc.selection.declared, "parse_failures": sc.selection.parse_failures,
        },
        "executable": {"first_try_executable": sc.executable.first_try_executable,
                       "error": sc.executable.error, "reason": sc.executable.reason},
        "correctness": _correctness_artifact(sc),
    }


def build_artifact(*, run_id: str, kind: str, suite: Suite, conditions: Sequence[Condition],
                   reps: int, model_id: str, backend: str,
                   snapshot_refs: dict[str, str], scored: Sequence[tuple[JourneyRecord, ScoredJourney]],
                   golden_executions: Sequence[dict], ga4_count: int,
                   started_at: str, ended_at: str) -> dict:
    kb_refs = {c.name: c.ref for c in conditions}
    cases_meta = [
        {"id": c.id, "request": c.request, "systems": list(c.systems),
         "visual_kind": c.visual_kind, "recurring": c.recurring,
         "expected_objects": list(c.expected_objects), "byte_stable": c.is_byte_stable,
         "blend": (c.blend or {}).get("kind") if c.blend else None}
        for c in suite.cases
    ]
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "cases_meta": cases_meta,
        "run": {
            "run_id": run_id, "kind": kind,
            "suite_version": suite.suite_version, "customer": suite.customer,
            "journey_prompt_version": JOURNEY_PROMPT_VERSION,
            "backend": backend, "model_id": model_id,
            "snapshot_refs": snapshot_refs, "kb_refs": kb_refs,
            "reps": reps, "cases": [c.id for c in suite.cases],
            "conditions": [c.name for c in conditions],
            "started_at": started_at, "ended_at": ended_at, "notes": R6_NOTE,
        },
        "ga4_execution_count": ga4_count,
        "golden_executions": list(golden_executions),
        "journeys": [journey_artifact(r, s) for r, s in scored],
    }


def score_records(records: Sequence[JourneyRecord], suite: Suite,
                  inventory: SnapshotInventory,
                  golden_results: Mapping[str, Mapping[str, Any]]
                  ) -> list[tuple[JourneyRecord, ScoredJourney]]:
    out = []
    for rec in records:
        case = suite.case(rec.case_id)
        sc = score_journey(rec, case, inventory, golden_results.get(rec.case_id))
        out.append((rec, sc))
    return out


def run_baseline(*, backend, suite: Suite, conditions: Sequence[Condition], reps: int,
                 inventory: SnapshotInventory, golden_cache, snapshot_refs: dict[str, str],
                 out_dir: Path, kind: str = "baseline",
                 cases: Sequence[Case] | None = None) -> dict:
    """Run cases × conditions × reps; checkpoint + score; write the artifact."""
    cases = list(cases or suite.cases)
    run_id = f"{kind}-{_dt.datetime.now(_dt.timezone.utc):%Y%m%dT%H%M%SZ}"
    run_dir = Path(out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = _now()
    scored: list[tuple[JourneyRecord, ScoredJourney]] = []
    for case in cases:
        golden = golden_cache.results_for(case)
        for cond in conditions:
            for rep in range(reps):
                rec = backend.run_journey(case, cond, rep)
                sc = score_journey(rec, case, inventory, golden)
                scored.append((rec, sc))
                (run_dir / f"{case.id}_{cond.name}_{rep}.json").write_text(
                    json.dumps(journey_artifact(rec, sc), indent=2, default=str), "utf-8")
    artifact = build_artifact(
        run_id=run_id, kind=kind, suite=suite, conditions=conditions, reps=reps,
        model_id=backend.model_id if hasattr(backend, "model_id") else "",
        backend=backend.id, snapshot_refs=snapshot_refs, scored=scored,
        golden_executions=golden_cache.executions, ga4_count=golden_cache.ga4_count,
        started_at=started, ended_at=_now())
    (run_dir / "results.json").write_text(json.dumps(artifact, indent=2, default=str), "utf-8")
    from benchmark.report import build_report
    (run_dir / "report.md").write_text(build_report(artifact), "utf-8")
    return artifact


def _main(argv: Sequence[str] | None = None) -> int:
    from benchmark.backends import ClaudeCodeBackend, GoldenCache, load_secrets
    from benchmark.executors import LiveExecutor
    from benchmark.suite import load_suite
    from benchmark.validate import DEFAULT_SNAPSHOTS, DEFAULT_SUITE, load_snapshots
    from benchmark.conditions import build_machine_kb, DEFAULT_ENRICHED_KB

    ap = argparse.ArgumentParser(description="Run the benchmark baseline (R9). Live LLM + data.")
    ap.add_argument("--backend", choices=["claude-code"], default="claude-code")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", type=Path, default=Path("results"))
    ap.add_argument("--workdir", type=Path, required=True, help="scratch workdir root (git-ignored)")
    ap.add_argument("--secrets", type=Path, default=Path(".secrets"))
    ap.add_argument("--enriched-kb", type=Path, default=DEFAULT_ENRICHED_KB)
    ap.add_argument("--cases", nargs="*", help="restrict to these case ids")
    args = ap.parse_args(argv)

    suite = load_suite(DEFAULT_SUITE)
    snaps = load_snapshots(DEFAULT_SNAPSHOTS)
    inventory = SnapshotInventory(snaps)
    snap_dir = Path(DEFAULT_SNAPSHOTS[0]).parent
    snapshot_refs = _snapshot_refs(snaps, snap_dir)
    secrets = load_secrets(args.secrets, snap_dir)

    def _cfg(p): return json.loads(Path(p).read_text()) if p and Path(p).is_file() else None
    golden_exec = LiveExecutor(supabase_dsn=secrets.supabase_dsn,
                               ga4_config=_cfg(secrets.ga4_config), gsc_config=_cfg(secrets.gsc_config))
    golden_cache = GoldenCache(golden_exec)

    import os
    mkb = build_machine_kb(args.workdir / "machine-kb", DEFAULT_SNAPSHOTS)
    conditions = [no_kb_condition(), mkb.condition(), enriched_kb_condition(args.enriched_kb)]
    backend = ClaudeCodeBackend(claude_path=os.environ["CLAUDE_CODE_EXECPATH"],
                                secrets=secrets, workdir_root=args.workdir / "journeys",
                                customer=suite.customer)
    cases = [suite.case(c) for c in args.cases] if args.cases else None
    artifact = run_baseline(backend=backend, suite=suite, conditions=conditions, reps=args.reps,
                            inventory=inventory, golden_cache=golden_cache,
                            snapshot_refs=snapshot_refs, out_dir=args.out, cases=cases)
    print(f"baseline {artifact['run']['run_id']}: {len(artifact['journeys'])} journeys, "
          f"ga4={artifact['ga4_execution_count']} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
