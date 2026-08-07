"""Thin batch driver for the CP-5 benchmark skill (deliverable 4).

Runs golden-suite journeys headlessly through Claude Code, one journey per
invocation of the skill, and writes each journey record where the **existing**
CP-2 harness ingests it — `benchmark.manual ingest` / `score`, unchanged.

    .venv/bin/python -m tools.benchmark_driver \
        --suite ~/Desktop/kb/.contextlayer/benchmark/suite.yaml \
        --condition enriched-kb=http://localhost:8100 \
        --condition machine-kb=http://localhost:8101 \
        --condition no-kb=http://localhost:8102 \
        --model claude-opus-4-8 \
        --runs ~/Desktop/cp5-runs \
        --smoke                      # one case, one condition, then stop

Deliberately thin. It does not score, does not decide what a journey means,
and does not touch `benchmark/` — the CP-5 fence keeps the CP-2 harness
byte-unchanged, so this driver's only job is to *invoke* and *place files*.
Everything downstream is the harness's, exactly as CP-2 built it.

**R2 fairness is structural here.** `--condition` varies the MCP endpoint
and nothing else; the prompt is loaded once and rendered identically for
every condition. If you ever find yourself wanting a per-condition prompt
flag, that is the fairness rule being violated, not a missing feature.

**Cost (ruling D-77).** AI usage cost is the operating user's
responsibility, in development and in the product alike. Skills run in the
customer's own Claude Code under their own licenses; the platform ships no
model, no keys, and no billing management. This driver gates nothing on
spend and asserts nothing about billing. `cost_usd` is passed through to
the journey record when the runtime reports it, informational only — and
when it is absent it stays absent, never coerced to zero.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ConditionEndpoint:
    name: str
    url: str


@dataclass(frozen=True)
class JourneySpec:
    case_id: str
    condition: str
    rep: int


def parse_conditions(specs: list[str]) -> list[ConditionEndpoint]:
    out: list[ConditionEndpoint] = []
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"--condition expects NAME=URL, got {spec!r}")
        name, url = spec.split("=", 1)
        out.append(ConditionEndpoint(name, url))
    return out


def plan_journeys(
    case_ids: list[str],
    conditions: list[ConditionEndpoint],
    reps: int,
    smoke: bool,
) -> list[JourneySpec]:
    """The run grid: cases x conditions x reps.

    `--smoke` collapses it to exactly one journey — the first case on the
    first condition. The smoke run is authorized separately from the batch
    (D-76.3d), so the driver must make "one journey, then stop" a single
    flag rather than a discipline the operator has to remember.
    """
    if smoke:
        return [JourneySpec(case_ids[0], conditions[0].name, 1)]
    return [
        JourneySpec(case_id, cond.name, rep)
        for case_id in case_ids
        for cond in conditions
        for rep in range(1, reps + 1)
    ]


def record_path(runs_root: Path, spec: JourneySpec) -> Path:
    """Where the harness's file ingestion expects to find a record."""
    return runs_root / spec.condition / f"{spec.case_id}-rep{spec.rep}.json"


def build_invocation(
    spec: JourneySpec,
    endpoint: ConditionEndpoint,
    model: str,
    prompt: str,
    setup_dir: Path,
) -> list[str]:
    """The headless Claude Code command for one journey.

    A fresh session per journey — no carry-over of resolved context
    between cases, which would leak the enriched condition's knowledge
    into later journeys and quietly inflate the thin conditions.
    """
    return [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--add-dir",
        str(setup_dir),
    ]


def extract_result(stream_json: str) -> dict:
    """Pull the terminal result object out of the CLI's stream-json output.

    `cost_usd` is carried through untouched when present and left absent
    when not (D-77.3) — "unknown" and "free" are different facts and the
    record must not blur them.
    """
    result: dict = {}
    for line in stream_json.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event
    out: dict = {"session_id": result.get("session_id", "")}
    if "total_cost_usd" in result:
        out["cost_usd"] = result["total_cost_usd"]
    if "usage" in result:
        out["tokens"] = result["usage"]
    return out


def run_journey(
    spec: JourneySpec,
    endpoint: ConditionEndpoint,
    model: str,
    prompt: str,
    setup_dir: Path,
    runs_root: Path,
    timeout_s: int,
    dry_run: bool,
) -> tuple[bool, str]:
    dest = record_path(runs_root, spec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_invocation(spec, endpoint, model, prompt, setup_dir)

    if dry_run:
        return True, f"[dry-run] {' '.join(cmd[:6])} … -> {dest}"

    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        return False, "`claude` not on PATH — headless Claude Code is required"
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout_s}s"

    if proc.returncode != 0:
        return False, f"exit {proc.returncode}: {proc.stderr.strip()[:200]}"

    meta = extract_result(proc.stdout)
    if not dest.exists():
        # The skill writes the record itself; if it did not, say so rather
        # than synthesizing one — a fabricated record would be scored as
        # if it were a real journey.
        return False, f"skill emitted no record at {dest}"

    record = json.loads(dest.read_text())
    record.setdefault("started_at", started)
    record.setdefault("ended_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    record.setdefault("model_id", model)
    record.setdefault("backend", "benchmark-skill-v1")
    for key, value in meta.items():
        record.setdefault(key, value)
    dest.write_text(json.dumps(record, indent=2) + "\n")

    return True, str(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Headless batch driver for the benchmark skill")
    ap.add_argument("--suite", type=Path, required=True, help="golden suite YAML")
    ap.add_argument("--condition", action="append", default=[], metavar="NAME=URL", required=True)
    ap.add_argument("--model", required=True, help="pinned model id (joins the R8 key)")
    ap.add_argument("--runs", type=Path, required=True, help="run root (OUTSIDE the repo)")
    ap.add_argument("--setup", type=Path, help="compiled profile dir (from `cli.js compile`)")
    ap.add_argument("--prompt", type=Path, default=Path("benchmark/prompts/journey-prompt-v1.md"))
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--smoke", action="store_true", help="one journey, then stop (D-76.3d)")
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true", help="print the plan; invoke nothing")
    args = ap.parse_args(argv)

    # CLAUDE.md ancestry contamination: a run root inside the repo injects
    # this repo's CLAUDE.md into every journey session. Same rule the CP-2
    # manual kit enforces (Makefile RUNS default).
    runs_root = args.runs.expanduser().resolve()
    if runs_root.is_relative_to(Path.cwd()):
        ap.error(f"--runs must live outside the repo (CLAUDE.md ancestry contamination): {runs_root}")

    try:
        conditions = parse_conditions(args.condition)
    except ValueError as exc:
        ap.error(str(exc))

    import yaml  # local: keeps the module importable without the dep

    suite = yaml.safe_load(args.suite.read_text())
    case_ids = [c["id"] for c in suite.get("cases", [])]
    if not case_ids:
        ap.error(f"no cases in {args.suite}")

    # R2 fairness: the prompt body and the per-condition CONTEXT_ACCESS
    # variants come from the harness's own loader/renderer, so this driver
    # cannot drift from what CP-2 measured. One body, three variants that
    # differ only in the access they describe.
    from benchmark.runner import load_prompt, render_prompt

    body, variants = load_prompt(args.prompt)
    customer = suite.get("customer", "the customer")
    systems = sorted({sys_name for c in suite.get("cases", []) for sys_name in c.get("systems", [])})
    missing = [c.name for c in conditions if c.name not in variants]
    if missing:
        ap.error(f"prompt has no CONTEXT-ACCESS variant for: {', '.join(missing)}")

    setup_dir = (args.setup or Path.cwd()).resolve()

    journeys = plan_journeys(case_ids, conditions, args.reps, args.smoke)
    by_name = {c.name: c for c in conditions}
    cases_by_id = {c["id"]: c for c in suite.get("cases", [])}

    print(
        f"{len(journeys)} journey(s) · model {args.model} · "
        f"{len(case_ids)} case(s) x {len(conditions)} condition(s) x {args.reps} rep(s)"
        + ("  [SMOKE: one journey, then stop]" if args.smoke else "")
    )

    failures = 0
    for spec in journeys:
        case = cases_by_id[spec.case_id]
        prompt = render_prompt(spec.condition, customer, case.get("systems", systems), body, variants)
        prompt = f"{prompt}\n\n## The request\n\n{case['request']}\n"
        ok, detail = run_journey(
            spec,
            by_name[spec.condition],
            args.model,
            prompt,
            setup_dir,
            runs_root,
            args.timeout_s,
            args.dry_run,
        )
        status = "ok " if ok else "FAIL"
        print(f"  [{status}] {spec.case_id} / {spec.condition} / rep{spec.rep}: {detail}")
        if not ok:
            failures += 1

    print(
        f"\n{len(journeys) - failures}/{len(journeys)} journeys recorded under {runs_root}\n"
        "score them with the CP-2 harness, unchanged:\n"
        f"  make ingest RUNS={runs_root}\n"
        f"  make score  RUNS={runs_root}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
