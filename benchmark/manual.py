"""Manual-baseline kit — operator-driven CP-2 baseline (dev tooling).

The CP-2 baseline is run by a human operator driving one *interactive*
Claude Code session per journey (subscription-billed), with execution through
``benchmark.mcp_executor``. Transport ruling points applied here:

* **record-to-file (2)** — the MCP executor's JSONL log is the authoritative
  per-journey trace; ``ingest`` folds it into an R3 ``JourneyRecord`` JSON
  under ``records/``. Fields the interactive transport cannot measure
  (token counts, cost, session id) are null; ``tool_calls`` counts executor
  calls only (not turns); timestamps come from the log file's birth/mtime.
* **executor guardrails (3)** — execution goes only through
  ``benchmark.mcp_executor`` (SELECT-only SQL, one API call per tool call,
  credentials in the server env, never the agent's).
* **isolation (5)** — ``conditions`` builds three sibling working
  directories, each containing ONLY an identical ``.mcp.json``, an empty
  ``records/``, and (for the KB conditions) the condition's KB under
  ``./kb``. The root must have no ``CLAUDE.md`` anywhere in its directory
  ancestry — interactive Claude Code walks ancestors for memory files, so
  the dirs live *outside* this repo (the repo root carries CLAUDE.md).
  A preflight enforces this and the no-stray-files invariant.
* **per-journey autonomy (7)** — one fresh session per journey; the exact
  operator sequence is in ``OPERATOR.md``.

Scoring reuses the harness unchanged: selection is parser-extracted from the
executed statements in the record (R4 — never the agent's self-declared
list), correctness compares same-run goldens (R5/D-53), first-try executable
per R6; the artifact/report are the R8/R9 machinery with backend id
``claude-code-interactive`` (a distinct R8 key from headless ``claude-code``;
one backend per baseline, R9/D-54).

No product code or specs are touched; this module is dev tooling under the
dev-runner boundary ruling.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from benchmark.backends import GoldenCache, apply_journey_log, load_secrets
from benchmark.baseline import _snapshot_refs, build_artifact
from benchmark.conditions import (
    DEFAULT_ENRICHED_KB,
    ENRICHED_KB,
    MACHINE_KB,
    NO_KB,
    Condition,
    _manifest_ref,
    _sha256_file,
    build_machine_kb,
)
from benchmark.executors import LiveExecutor
from benchmark.fqn import SnapshotInventory
from benchmark.journey import JourneyRecord
from benchmark.runner import DEFAULT_MODEL_ID, load_prompt, render_prompt
from benchmark.scoring import score_journey
from benchmark.suite import Suite, load_suite
from benchmark.validate import DEFAULT_SNAPSHOTS, DEFAULT_SUITE, load_snapshots

# The suite is the customer's and lives in their KB (D-119.2a); every
# command that reads it takes the path, so a second KB (or the frozen
# harness fixture) is a flag rather than an edit.
_SUITE_HELP = "golden suite (default: the KB's .contextlayer/benchmark/suite.yaml)"

_PKG = Path(__file__).resolve().parent
REPO = _PKG.parent
MANUAL_PROMPT_PATH = _PKG / "prompts" / "journey-prompt-v1-manual.md"
JOURNEY_PROMPT_VERSION = "v1"  # manual file is a transport variant, not a new version
BACKEND_ID = "claude-code-interactive"
CONDITIONS = (NO_KB, MACHINE_KB, ENRICHED_KB)
DEFAULT_ROOT = Path.home() / "Desktop" / "cp2-runs"
MANIFEST_NAME = "manifest.json"

_RECORD_RE = re.compile(
    r"^(?P<case>[A-Za-z0-9_-]+)\.(?P<cond>" + "|".join(CONDITIONS) + r")\.(?P<rep>\d+)\.(?P<ext>jsonl|json)$"
)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).isoformat()


def _os_noise(p: Path) -> bool:
    """Finder droppings — not condition content, ignored by every check.

    macOS writes .DS_Store/._* into any browsed directory; a multi-day
    manual campaign would otherwise trip the drift guard spuriously.
    """
    return p.name == ".DS_Store" or p.name.startswith("._")


def _tree_ref(root: Path) -> str:
    """conditions.py's manifest hash over an arbitrary tree (integrity ref)."""
    manifest = {
        p.relative_to(root).as_posix(): _sha256_file(p)
        for p in sorted(root.rglob("*")) if p.is_file() and not _os_noise(p)
    }
    return _manifest_ref(manifest)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _repo_ref(repo: Path) -> str:
    try:
        head = _git(repo, "rev-parse", "HEAD")
        dirty = _git(repo, "status", "--porcelain")
        return head + ("-dirty" if dirty else "")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


# --------------------------------------------------------------------------
# preflight — session-context isolation (transport ruling point 5)


def preflight(root: Path) -> list[str]:
    """Context-contamination checks; returns problems (empty = clean).

    Interactive Claude Code loads ``CLAUDE.md`` from the cwd's directory
    ancestry and from ``~/.claude/CLAUDE.md``, and nested ``CLAUDE.md``
    files when reading a subtree. Any of those in reach of a condition dir
    injects non-condition context into the journey.
    """
    problems: list[str] = []
    root = root.resolve()
    for anc in [root, *root.parents]:
        for name in ("CLAUDE.md", "CLAUDE.local.md"):
            if (anc / name).is_file():
                problems.append(f"{anc / name} would be auto-loaded into every session "
                                f"(ancestor memory walk) — pick a root outside it")
    user_memory = Path.home() / ".claude" / "CLAUDE.md"
    if user_memory.is_file():
        problems.append(f"{user_memory} (user memory) loads into every session — "
                        f"move it aside for the baseline")
    for cond in CONDITIONS:
        cdir = root / cond
        if cdir.is_dir():
            for p in cdir.rglob("CLAUDE*.md"):
                problems.append(f"{p} inside a condition dir — nested memory injection")
    return problems


def _verify_condition_dir(cdir: Path, *, expect_kb: bool) -> list[str]:
    """The no-stray-files invariant: ONLY .mcp.json, records/, and kb/."""
    problems: list[str] = []
    allowed_top = {".mcp.json", "records"} | ({"kb"} if expect_kb else set())
    for entry in sorted(cdir.iterdir()):
        if entry.name not in allowed_top and not _os_noise(entry):
            problems.append(f"stray entry in {cdir.name}/: {entry.name}")
    if expect_kb and not (cdir / "kb").is_dir():
        problems.append(f"{cdir.name}/kb missing")
    if not expect_kb and (cdir / "kb").exists():
        problems.append(f"{cdir.name}/kb must not exist (no-kb condition)")
    for p in cdir.rglob("*"):
        if p.name in ("CLAUDE.md", "CLAUDE.local.md") or ".git" in p.parts:
            problems.append(f"forbidden file under {cdir.name}/: {p.relative_to(cdir)}")
    return problems


# --------------------------------------------------------------------------
# conditions — deliverable 1


def _mcp_config_text() -> str:
    """The single .mcp.json, byte-identical across the three condition dirs.

    ``${VAR}`` values are expanded by Claude Code from the operator's shell
    at session start: SUPABASE_DSN comes from sourcing .secrets/env.sh,
    BENCHMARK_JOURNEY_LOG is exported per journey (no default on purpose —
    a forgotten export fails the server loudly instead of dropping the
    record), and ${PWD}/kb resolves to the condition dir's KB (absent in
    no-kb, where list_context then returns no documents).
    """
    cfg = {
        "mcpServers": {
            "executor": {
                "command": sys.executable,
                "args": ["-m", "benchmark.mcp_executor"],
                "env": {
                    "PYTHONPATH": str(REPO),
                    "BENCHMARK_JOURNEY_LOG": "${BENCHMARK_JOURNEY_LOG}",
                    "BENCHMARK_SNAPSHOTS_DIR": str(_PKG / "suite" / "snapshots"),
                    "BENCHMARK_SUPABASE_DSN": "${SUPABASE_DSN}",
                    "BENCHMARK_GA4_CONFIG": str(REPO / ".secrets" / "ga4-live.json"),
                    "BENCHMARK_GSC_CONFIG": str(REPO / ".secrets" / "gsc-live.json"),
                    "BENCHMARK_CONTEXT_ROOT": "${PWD}/kb",
                },
            }
        }
    }
    return json.dumps(cfg, indent=2) + "\n"


def _export_enriched_kb(src: Path, ref: str, dest: Path) -> str:
    """Export the customer KB working tree at a pinned ref (no .git). -> sha"""
    sha = _git(src, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    tar_bytes = subprocess.run(["git", "-C", str(src), "archive", "--format=tar", sha],
                               capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
        tf.extractall(dest, filter="data")
    return sha


def cmd_conditions(args: argparse.Namespace) -> int:
    root: Path = args.root
    problems = preflight(root)
    if problems:
        for p in problems:
            print(f"[PREFLIGHT] {p}")
        return 2

    existing = [c for c in CONDITIONS if (root / c).exists()]
    if existing and not args.force:
        print(f"condition dirs exist under {root} ({', '.join(existing)}); "
              f"re-run with --force to rebuild (records/ are preserved)")
        return 2

    root.mkdir(parents=True, exist_ok=True)
    mcp_text = _mcp_config_text()

    # machine-kb: deterministic render from the SAME snapshots the manifest
    # records below (R1). Reading the module default here instead would let
    # the rendered condition and its recorded provenance come from two
    # different places — the fan-out rule, in one function.
    snapshot_paths = args.snapshots or list(DEFAULT_SNAPSHOTS)
    mkb = build_machine_kb(root / MACHINE_KB / "kb", snapshot_paths)

    # enriched-kb: the customer KB exported at a pinned kb_ref.
    kb_sha = _export_enriched_kb(args.kb, args.kb_ref, root / ENRICHED_KB / "kb")
    enriched_tree = _tree_ref(root / ENRICHED_KB / "kb")

    for cond in CONDITIONS:
        cdir = root / cond
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "records").mkdir(exist_ok=True)
        (cdir / ".mcp.json").write_text(mcp_text, encoding="utf-8")

    problems = []
    for cond in CONDITIONS:
        problems += _verify_condition_dir(root / cond, expect_kb=cond != NO_KB)
    if problems:
        for p in problems:
            print(f"[INVARIANT] {p}")
        return 2

    snaps = load_snapshots(snapshot_paths)
    snap_dir = Path(snapshot_paths[0]).parent
    manifest = {
        "kit": "cp2-manual-baseline",
        "created_at": _now(),
        "runs_root": str(root),
        "repo": str(REPO),
        "repo_ref": _repo_ref(REPO),
        "backend": BACKEND_ID,
        "model_id": args.model,
        "journey_prompt": {
            "version": JOURNEY_PROMPT_VERSION,
            "file": str(MANUAL_PROMPT_PATH.relative_to(REPO)),
            "sha256": _sha256_file(MANUAL_PROMPT_PATH),
        },
        "snapshots_dir": str(snap_dir),
        "snapshot_refs": _snapshot_refs(snaps, snap_dir),
        "kb_refs": {
            NO_KB: "live-discovery",
            MACHINE_KB: mkb.ref,
            ENRICHED_KB: kb_sha,
        },
        "enriched_kb_source": str(args.kb),
        "enriched_tree_sha": enriched_tree,
        "mcp_sha256": "sha256:" + hashlib.sha256(mcp_text.encode("utf-8")).hexdigest(),
        "conditions": list(CONDITIONS),
    }
    (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"conditions built under {root}")
    print(f"  no-kb:       .mcp.json + records/ (live discovery)")
    print(f"  machine-kb:  {len(mkb.files)} machine files · ref {mkb.ref[:23]}…")
    print(f"  enriched-kb: kb_ref {kb_sha}")
    print(f"  manifest:    {root / MANIFEST_NAME}")
    return 0


# --------------------------------------------------------------------------
# prompt — deliverable 5 (render the paste-ready per-journey prompt)


def render_manual_prompt(suite: Suite, case_id: str, condition: str) -> str:
    if condition not in CONDITIONS:
        raise SystemExit(f"unknown condition {condition!r} (one of {', '.join(CONDITIONS)})")
    try:
        case = suite.case(case_id)
    except KeyError:
        raise SystemExit(f"unknown case {case_id!r} (suite has "
                         f"{', '.join(c.id for c in suite.cases)})") from None
    body, variants = load_prompt(MANUAL_PROMPT_PATH)
    rendered = render_prompt(condition, suite.customer, case.systems, body, variants)
    return (f"{rendered}\n---\n\n## The customer's request\n\n{case.request.strip()}\n")


def cmd_prompt(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    sys.stdout.write(render_manual_prompt(suite, args.case, args.condition))
    return 0


# --------------------------------------------------------------------------
# ingest — deliverable 2 (JSONL executor logs -> R3 records)


def record_from_log(log_path: Path, case_id: str, condition: str, rep: int,
                    model_id: str) -> JourneyRecord:
    """Assemble the R3 record from the executor's JSONL log.

    Interactive transport: tokens/cost/session are unmeasurable -> null;
    started/ended come from the log file's birth/mtime; tool_calls counts
    executor calls (the log entries), not conversation turns.
    """
    stat = log_path.stat()
    entries = [ln for ln in log_path.read_text("utf-8").splitlines() if ln.strip()]
    record = JourneyRecord(
        case_id=case_id, condition=condition, rep=rep, model_id=model_id,
        backend=BACKEND_ID, cost_usd=None, session_id="",
        started_at=_iso(getattr(stat, "st_birthtime", stat.st_mtime)),
        ended_at=_iso(stat.st_mtime),
        tokens={"input_tokens": None, "output_tokens": None,
                "cache_read_input_tokens": None, "cache_creation_input_tokens": None},
        tool_calls=len(entries),
    )
    apply_journey_log(record, log_path)
    return record


def _validate_log(log_path: Path) -> list[str]:
    problems = []
    finishes = execs = 0
    for ln in log_path.read_text("utf-8").splitlines():
        if not ln.strip():
            continue
        try:
            kind = json.loads(ln).get("kind")
        except json.JSONDecodeError:
            problems.append(f"{log_path.name}: unparseable JSONL line")
            return problems
        finishes += kind == "finish"
        execs += kind == "exec"
    if finishes > 1:
        problems.append(f"{log_path.name}: {finishes} finish entries — two sessions "
                        f"likely wrote to one log; discard and rerun the journey")
    if execs == 0:
        problems.append(f"{log_path.name}: no executed request in the log")
    return problems


def cmd_ingest(args: argparse.Namespace) -> int:
    root: Path = args.root
    manifest = _load_manifest(root)
    suite = load_suite(args.suite)
    model_id = manifest["model_id"]
    done = skipped = 0
    errors: list[str] = []
    for cond in CONDITIONS:
        rec_dir = root / cond / "records"
        if not rec_dir.is_dir():
            continue
        for log_path in sorted(rec_dir.glob("*.jsonl")):
            m = _RECORD_RE.match(log_path.name)
            if not m:
                errors.append(f"{cond}/records/{log_path.name}: name must be "
                              f"{{case_id}}.{{condition}}.{{rep}}.jsonl")
                continue
            if m["cond"] != cond:
                errors.append(f"{cond}/records/{log_path.name}: filename condition "
                              f"{m['cond']!r} does not match its directory")
                continue
            try:
                suite.case(m["case"])
            except KeyError:
                errors.append(f"{cond}/records/{log_path.name}: unknown case {m['case']!r}")
                continue
            out = log_path.with_suffix(".json")
            if out.exists() and not args.force:
                skipped += 1
                continue
            log_problems = _validate_log(log_path)
            if log_problems:
                errors.extend(log_problems)
                continue
            record = record_from_log(log_path, m["case"], cond, int(m["rep"]), model_id)
            out.write_text(json.dumps(record.to_dict(), indent=2, default=str) + "\n",
                           encoding="utf-8")
            done += 1
    for e in errors:
        print(f"[INGEST] {e}")
    print(f"ingested {done} record(s), {skipped} already ingested, {len(errors)} error(s)")
    return 1 if errors else 0


# --------------------------------------------------------------------------
# score — deliverable 2 (validate + score records/*.json -> R8 artifact)


def _load_manifest(root: Path) -> dict:
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise SystemExit(f"no {MANIFEST_NAME} under {root} — run `make conditions` first")
    return json.loads(path.read_text("utf-8"))


def collect_records(root: Path, suite: Suite) -> tuple[list[JourneyRecord], list[str]]:
    """Load and validate records/*.json from all three condition dirs."""
    records: list[JourneyRecord] = []
    errors: list[str] = []
    seen: dict[tuple[str, str, int], str] = {}
    for cond in CONDITIONS:
        rec_dir = root / cond / "records"
        if not rec_dir.is_dir():
            continue
        for path in sorted(rec_dir.glob("*.json")):
            where = f"{cond}/records/{path.name}"
            m = _RECORD_RE.match(path.name)
            if not m:
                errors.append(f"{where}: name must be {{case_id}}.{{condition}}.{{rep}}.json")
                continue
            try:
                rec = JourneyRecord.from_dict(json.loads(path.read_text("utf-8")))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                errors.append(f"{where}: not a valid R3 record ({exc})")
                continue
            if (rec.case_id, rec.condition, rec.rep) != (m["case"], m["cond"], int(m["rep"])):
                errors.append(f"{where}: filename does not match record fields "
                              f"({rec.case_id}.{rec.condition}.{rec.rep})")
                continue
            if rec.condition != cond:
                errors.append(f"{where}: record condition {rec.condition!r} "
                              f"does not match its directory")
                continue
            try:
                suite.case(rec.case_id)
            except KeyError:
                errors.append(f"{where}: unknown case {rec.case_id!r}")
                continue
            if rec.backend != BACKEND_ID:
                errors.append(f"{where}: backend {rec.backend!r} != {BACKEND_ID!r} "
                              f"(one backend per baseline, R9)")
                continue
            key = (rec.case_id, rec.condition, rec.rep)
            if key in seen:
                errors.append(f"{where}: duplicate journey key (also {seen[key]})")
                continue
            seen[key] = where
            if not rec.drafts:
                print(f"[WARN] {where}: record has no executed drafts")
            records.append(rec)
        pending = [p.name for p in sorted(rec_dir.glob("*.jsonl"))
                   if not p.with_suffix(".json").exists()]
        for name in pending:
            print(f"[WARN] {cond}/records/{name}: JSONL not ingested yet (run ingest)")
    return records, errors


def _verify_unchanged(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    problems = []
    for cond in CONDITIONS:
        mcp = root / cond / ".mcp.json"
        if not mcp.is_file():
            problems.append(f"{cond}/.mcp.json missing")
        elif _sha256_file(mcp) != manifest["mcp_sha256"]:
            problems.append(f"{cond}/.mcp.json changed since the build")
    mkb = root / MACHINE_KB / "kb"
    if _tree_ref(mkb) != manifest["kb_refs"][MACHINE_KB]:
        problems.append("machine-kb/kb tree changed since the build")
    ekb = root / ENRICHED_KB / "kb"
    if _tree_ref(ekb) != manifest["enriched_tree_sha"]:
        problems.append("enriched-kb/kb tree changed since the build")
    return problems


def cmd_score(args: argparse.Namespace) -> int:
    root: Path = args.root
    manifest = _load_manifest(root)
    suite = load_suite(args.suite)
    snaps = load_snapshots(args.snapshots or list(DEFAULT_SNAPSHOTS))
    inventory = SnapshotInventory(snaps)

    drift = _verify_unchanged(root, manifest)
    if drift:
        for p in drift:
            print(f"[DRIFT] {p}")
        return 2

    records, errors = collect_records(root, suite)
    for e in errors:
        print(f"[INVALID] {e}")
    if errors:
        return 1
    if not records:
        print("no records to score")
        return 1

    model_ids = sorted({r.model_id for r in records})
    if len(model_ids) > 1:
        print(f"[INVALID] mixed model ids across records: {model_ids}")
        return 1
    if model_ids != [manifest["model_id"]]:
        print(f"[WARN] records model {model_ids[0]!r} != manifest pin "
              f"{manifest['model_id']!r}")

    # same-run goldens (R5) — each present case's golden legs execute once.
    cases_present = sorted({r.case_id for r in records})
    golden_results: dict[str, Any] = {}
    golden_executions: list[dict] = []
    ga4_count = 0
    if not args.no_golden:
        secrets = load_secrets(args.secrets, Path(manifest["snapshots_dir"]))

        def _cfg(p):
            return json.loads(Path(p).read_text()) if p and Path(p).is_file() else None

        cache = GoldenCache(LiveExecutor(supabase_dsn=secrets.supabase_dsn,
                                         ga4_config=_cfg(secrets.ga4_config),
                                         gsc_config=_cfg(secrets.gsc_config)))
        for cid in cases_present:
            golden_results[cid] = cache.results_for(suite.case(cid))
        golden_executions = cache.executions
        ga4_count = cache.ga4_count

    started = _now()
    scored = [(rec, score_journey(rec, suite.case(rec.case_id), inventory,
                                  golden_results.get(rec.case_id)))
              for rec in records]

    conditions = [
        Condition(NO_KB, None, manifest["kb_refs"][NO_KB]),
        Condition(MACHINE_KB, root / MACHINE_KB / "kb", manifest["kb_refs"][MACHINE_KB]),
        Condition(ENRICHED_KB, root / ENRICHED_KB / "kb", manifest["kb_refs"][ENRICHED_KB]),
    ]
    reps = max(r.rep for r in records) + 1
    run_id = f"manual-{_dt.datetime.now(_dt.timezone.utc):%Y%m%dT%H%M%SZ}"
    artifact = build_artifact(
        run_id=run_id, kind="manual-baseline", suite=suite, conditions=conditions,
        reps=reps, model_id=model_ids[0], backend=BACKEND_ID,
        snapshot_refs=manifest["snapshot_refs"], scored=scored,
        golden_executions=golden_executions, ga4_count=ga4_count,
        started_at=started, ended_at=_now())
    artifact["run"]["notes"] += (
        " Manual transport: interactive Claude Code sessions per OPERATOR.md; "
        f"prompt file {manifest['journey_prompt']['file']} (v1 variant); "
        "tokens/cost null (unmeasurable); tool_calls = executor calls only."
    )

    run_dir = Path(args.out) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(json.dumps(artifact, indent=2, default=str), "utf-8")
    from benchmark.report import build_report
    (run_dir / "report.md").write_text(build_report(artifact), "utf-8")

    expected = len(suite.cases) * len(CONDITIONS) * reps
    print(f"scored {len(records)} journey(s) across {len(cases_present)} case(s) "
          f"({len(records)}/{expected} of a {reps}-rep full grid) — "
          f"golden legs executed: {len(golden_executions)}, ga4={ga4_count}")
    print(f"  results: {run_dir / 'results.json'}")
    print(f"  report:  {run_dir / 'report.md'}")
    return 0


# --------------------------------------------------------------------------
# status — coverage of the cases × conditions × reps grid


def cmd_status(args: argparse.Namespace) -> int:
    root: Path = args.root
    suite = load_suite(args.suite)
    have: dict[tuple[str, str], set[int]] = {}
    for cond in CONDITIONS:
        rec_dir = root / cond / "records"
        if not rec_dir.is_dir():
            continue
        for path in rec_dir.glob("*.json*"):
            m = _RECORD_RE.match(path.name)
            if m and m["cond"] == cond:
                have.setdefault((m["case"], cond), set()).add(int(m["rep"]))
    total = missing = 0
    print(f"{'case':8} " + " ".join(f"{c:>12}" for c in CONDITIONS))
    for case in suite.cases:
        row = []
        for cond in CONDITIONS:
            reps = have.get((case.id, cond), set())
            total += len(reps & set(range(args.reps)))
            miss = sorted(set(range(args.reps)) - reps)
            missing += len(miss)
            row.append(f"{len(reps)}/{args.reps}" + (f" (-{','.join(map(str, miss))})" if miss else ""))
        print(f"{case.id:8} " + " ".join(f"{c:>12}" for c in row))
    print(f"journeys recorded: {total} · missing: {missing} "
          f"(grid = {len(suite.cases)}×{len(CONDITIONS)}×{args.reps})")
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    problems = preflight(args.root)
    for cond in CONDITIONS:
        cdir = args.root / cond
        if cdir.is_dir():
            problems += _verify_condition_dir(cdir, expect_kb=cond != NO_KB)
    for p in problems:
        print(f"[PREFLIGHT] {p}")
    print("preflight OK" if not problems else f"preflight FAILED ({len(problems)})")
    return 0 if not problems else 2


# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CP-2 manual-baseline kit (operator-driven).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("conditions", help="build the three condition working dirs")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--snapshot", type=Path, action="append", dest="snapshots",
                   help="accepted snapshots to render machine-kb from (default: the KB's)")
    p.add_argument("--kb", type=Path, default=DEFAULT_ENRICHED_KB,
                   help="customer KB clone to export for enriched-kb")
    p.add_argument("--kb-ref", default="HEAD", help="ref to pin the enriched KB at")
    p.add_argument("--model", default=DEFAULT_MODEL_ID)
    p.add_argument("--force", action="store_true",
                   help="rebuild kb/.mcp.json in place (records/ preserved)")
    p.set_defaults(fn=cmd_conditions)

    p = sub.add_parser("prompt", help="print the paste-ready per-journey prompt")
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE, help=_SUITE_HELP)
    p.add_argument("--case", required=True)
    p.add_argument("--condition", required=True, choices=CONDITIONS)
    p.set_defaults(fn=cmd_prompt)

    p = sub.add_parser("ingest", help="assemble R3 records from executor JSONL logs")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE, help=_SUITE_HELP)
    p.add_argument("--force", action="store_true", help="re-ingest over existing .json")
    p.set_defaults(fn=cmd_ingest)

    p = sub.add_parser("score", help="validate + score records, write R8 artifact + report")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE, help=_SUITE_HELP)
    p.add_argument("--snapshot", type=Path, action="append", dest="snapshots",
                   help="accepted snapshots to resolve goldens against (default: the KB's)")
    p.add_argument("--out", type=Path, default=REPO / "results")
    p.add_argument("--secrets", type=Path, default=REPO / ".secrets")
    p.add_argument("--no-golden", action="store_true",
                   help="skip live golden execution (correctness unscored)")
    p.set_defaults(fn=cmd_score)

    p = sub.add_parser("status", help="coverage of the cases × conditions × reps grid")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE, help=_SUITE_HELP)
    p.add_argument("--reps", type=int, default=3)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("preflight", help="re-check isolation + dir invariants")
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.set_defaults(fn=cmd_preflight)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
