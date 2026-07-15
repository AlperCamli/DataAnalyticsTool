"""Runner backends behind one interface (R3, amended).

The ``JourneyRecord`` is the backend-agnostic contract. Two backends:

* **Backend A — ``api``** (``ApiBackend``): the direct Anthropic tool loop
  (``runner.run_journey``); needs an API key.
* **Backend B — ``claude-code``** (``ClaudeCodeBackend``): headless Claude
  Code (``claude -p``, ``--output-format stream-json``, pinned ``--model``,
  fresh session per journey). Executors are a local MCP server
  (``benchmark.mcp_executor``); ``--allowedTools`` is ``Read`` + the
  executor tools only (no Bash). Credentials live only in the MCP server's
  ``.mcp.json`` env — the agent process never has them and has no tool to
  read them. Per-journey checkpoint; auto-resume across subscription
  rate-limit windows; concurrency 1. ``total_cost_usd`` and usage are read
  from the CLI JSON into the record.

One backend per baseline (its id joins the R8 key); cross-backend
comparison is out of scope.

Golden legs are executed once per run (``GoldenCache``) via ``LiveExecutor``
and reused across a case's journeys for R5 correctness scoring.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from benchmark.conditions import NO_KB, Condition
from benchmark.executors import LiveExecutor
from benchmark.journey import Draft, ExecutionOutcome, JourneyRecord
from benchmark.runner import (
    DEFAULT_MODEL_ID,
    _mark_final,
    _now,
    _sql_system,
    load_prompt,
    render_prompt,
    run_journey,
)
from benchmark.scoring import LegResult
from benchmark.suite import Case

_SQL_SYSTEMS = frozenset({"supabase"})
_RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "overloaded", "429", "usage limit")


class Backend(Protocol):
    id: str
    def run_journey(self, case: Case, condition: Condition, rep: int) -> JourneyRecord: ...


# --------------------------------------------------------------------------
# secrets + golden execution (shared)


@dataclass
class Secrets:
    supabase_dsn: str | None = None
    ga4_config: str | None = None   # path to the GA4 connector config json
    gsc_config: str | None = None   # path to the GSC connector config json
    snapshots_dir: str | None = None


def load_secrets(secrets_dir: Path, snapshots_dir: Path) -> Secrets:
    """Read the DSN from env.sh + the GA4/GSC config paths (never echoed)."""
    dsn = None
    env_sh = secrets_dir / "env.sh"
    if env_sh.is_file():
        for line in env_sh.read_text("utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[len("export "):]
            if line.startswith("SUPABASE_DSN="):
                dsn = line.split("=", 1)[1].strip().strip('"').strip("'")
    def _p(name: str) -> str | None:
        p = secrets_dir / name
        return str(p) if p.is_file() else None
    return Secrets(supabase_dsn=dsn, ga4_config=_p("ga4-live.json"),
                   gsc_config=_p("gsc-live.json"), snapshots_dir=str(snapshots_dir))


class GoldenCache:
    """Executes each case's golden legs once per run; caches by (case, system)."""

    def __init__(self, executor: LiveExecutor):
        self._executor = executor
        self._cache: dict[tuple[str, str], LegResult] = {}
        self.executions: list[dict[str, Any]] = []  # audit: one entry per executed leg

    def results_for(self, case: Case) -> dict[str, LegResult]:
        out: dict[str, LegResult] = {}
        for leg in case.golden:
            key = (case.id, leg.system)
            if key not in self._cache:
                self._cache[key] = self._execute(case.id, leg)
            out[leg.system] = self._cache[key]
        return out

    def _execute(self, case_id: str, leg) -> LegResult:
        req = leg.request
        if leg.dialect == "sql":
            res = self._executor.run_sql(leg.system, req.get("statement", ""))
        else:
            res = self._executor.run_api(leg.system, req.get("operation", ""),
                                         req.get("property", ""), req.get("body", {}))
        self.executions.append({"case_id": case_id, "system": leg.system,
                                "dialect": leg.dialect, "ok": res.ok,
                                "row_count": res.row_count, "error": res.error,
                                "executed_at": _now()})
        return LegResult(columns=res.columns, rows=res.rows)

    @property
    def ga4_count(self) -> int:
        return sum(1 for e in self.executions if e["system"] == "ga4")


# --------------------------------------------------------------------------
# Backend A — direct API tool loop


class ApiBackend:
    id = "api"

    def __init__(self, model_client, snapshots: Sequence[Mapping[str, Any]], executor,
                 *, model_id: str = DEFAULT_MODEL_ID, customer: str = "the customer"):
        self._model_client = model_client
        self._snapshots = snapshots
        self._executor = executor
        self._model_id = model_id
        self._customer = customer
        self._prompt = load_prompt()

    def run_journey(self, case: Case, condition: Condition, rep: int) -> JourneyRecord:
        rec = run_journey(case, condition, rep, model_client=self._model_client,
                          executor=self._executor, snapshots=self._snapshots,
                          prompt=self._prompt, model_id=self._model_id, customer=self._customer)
        rec.backend = self.id
        return rec


# --------------------------------------------------------------------------
# Backend B — headless Claude Code


def _backend_b_system(case: Case, condition: Condition, customer: str,
                      prompt: tuple[str, Mapping[str, str]]) -> str:
    body, variants = prompt
    journey = render_prompt(condition.name, customer, case.systems, body, variants)
    lines = ["", "## Tools available this run"]
    if condition.name == NO_KB:
        lines.append("- `mcp__executor__discover_schema(system)`: introspect a system live.")
    else:
        lines.append("- `mcp__executor__list_context()`: list knowledge-base documents.")
        lines.append("- `Read(file_path)`: read a document (use the absolute paths list_context returns).")
    if any(s in _SQL_SYSTEMS for s in case.systems):
        lines.append("- `mcp__executor__run_sql(statement)`: one SELECT-only query.")
    if "ga4" in case.systems:
        lines.append("- `mcp__executor__run_ga4_report(property, body)`: one GA4 runReport.")
    if "gsc" in case.systems:
        lines.append("- `mcp__executor__run_gsc_query(property, body)`: one GSC query.")
    lines.append("- `mcp__executor__finish(objects, answer)`: call this LAST to finalize.")
    lines.append("Use only these tools. When your executed query answers the question, call finish.")
    return journey + "\n" + "\n".join(lines)


@dataclass
class ClaudeCodeBackend:
    claude_path: str
    secrets: Secrets
    workdir_root: Path
    model_id: str = DEFAULT_MODEL_ID
    customer: str = "the customer"
    max_resumes: int = 6
    resume_wait_s: float = 900.0
    call_timeout_s: float = 900.0
    id: str = field(default="claude-code", init=False)

    def __post_init__(self):
        self._prompt = load_prompt()
        Path(self.workdir_root).mkdir(parents=True, exist_ok=True)

    def _write_mcp_config(self, workdir: Path, journey_log: Path, context_root: Path | None) -> Path:
        env = {"BENCHMARK_JOURNEY_LOG": str(journey_log),
               "BENCHMARK_SNAPSHOTS_DIR": self.secrets.snapshots_dir or ""}
        if self.secrets.supabase_dsn:
            env["BENCHMARK_SUPABASE_DSN"] = self.secrets.supabase_dsn
        if self.secrets.ga4_config:
            env["BENCHMARK_GA4_CONFIG"] = self.secrets.ga4_config
        if self.secrets.gsc_config:
            env["BENCHMARK_GSC_CONFIG"] = self.secrets.gsc_config
        if context_root is not None:
            env["BENCHMARK_CONTEXT_ROOT"] = str(context_root)
        cfg = {"mcpServers": {"executor": {
            "command": _venv_python(),
            "args": ["-m", "benchmark.mcp_executor"], "env": env}}}
        path = workdir / ".mcp.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return path

    def _invoke(self, workdir: Path, request: str, system_prompt: str,
                mcp_path: Path, context_root: Path | None) -> tuple[str, str, int]:
        cmd = [self.claude_path, "-p", request,
               "--append-system-prompt", system_prompt,
               "--model", self.model_id,
               "--output-format", "stream-json", "--verbose",
               "--mcp-config", str(mcp_path), "--strict-mcp-config",
               "--allowedTools", "Read", "mcp__executor"]
        if context_root is not None:
            cmd += ["--add-dir", str(context_root)]
        try:
            proc = subprocess.run(cmd, cwd=str(workdir), capture_output=True, text=True,
                                  timeout=self.call_timeout_s)
            return proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            return (exc.stdout or "") if isinstance(exc.stdout, str) else "", \
                   f"timeout after {self.call_timeout_s}s", 124

    def run_journey(self, case: Case, condition: Condition, rep: int) -> JourneyRecord:
        workdir = Path(self.workdir_root) / f"{case.id}_{condition.name}_{rep}"
        if workdir.exists():
            for p in sorted(workdir.rglob("*"), reverse=True):
                p.unlink() if p.is_file() else p.rmdir()
        workdir.mkdir(parents=True, exist_ok=True)
        journey_log = workdir / "journey.jsonl"
        journey_log.write_text("", encoding="utf-8")
        context_root = None if condition.name == NO_KB else condition.context_root
        mcp_path = self._write_mcp_config(workdir, journey_log, context_root)
        system_prompt = _backend_b_system(case, condition, self.customer, self._prompt)

        started = _now()
        stdout = stderr = ""
        for attempt in range(self.max_resumes + 1):
            stdout, stderr, code = self._invoke(workdir, case.request, system_prompt, mcp_path, context_root)
            (workdir / "stdout.jsonl").write_text(stdout, encoding="utf-8")
            (workdir / "stderr.txt").write_text(stderr, encoding="utf-8")
            meta = _parse_stream(stdout)
            if not _is_rate_limited(meta, stderr) or attempt >= self.max_resumes:
                break
            time.sleep(self.resume_wait_s)  # subscription window auto-resume
            journey_log.write_text("", encoding="utf-8")  # fresh session, fresh log

        record = _assemble_record(case, condition, rep, self.model_id, self.id,
                                  started, journey_log, stdout)
        (workdir / "record.json").write_text(json.dumps(record.to_dict(), indent=2, default=str),
                                             encoding="utf-8")
        return record


def _venv_python() -> str:
    import sys
    return sys.executable


# --------------------------------------------------------------------------
# parsing + record assembly


def _parse_stream(stdout: str) -> dict[str, Any]:
    """Extract the CLI result meta + Read-based context reads from stream-json."""
    result: dict[str, Any] = {}
    reads: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result":
            result = obj
        elif obj.get("type") == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read":
                    fp = (block.get("input") or {}).get("file_path")
                    if fp:
                        reads.append(f"read:{fp}")
    result["_reads"] = reads
    return result


def _is_rate_limited(meta: Mapping[str, Any], stderr: str) -> bool:
    if meta.get("is_error"):
        blob = json.dumps(meta).lower() + " " + stderr.lower()
        return any(m in blob for m in _RATE_LIMIT_MARKERS)
    return False


def _assemble_record(case, condition, rep, model_id, backend, started,
                     journey_log: Path, stdout: str) -> JourneyRecord:
    meta = _parse_stream(stdout)
    usage = meta.get("usage", {}) or {}
    record = JourneyRecord(
        case_id=case.id, condition=condition.name, rep=rep, model_id=model_id,
        backend=backend, cost_usd=meta.get("total_cost_usd"),
        session_id=meta.get("session_id", ""), started_at=started, ended_at=_now(),
        notes=str(meta.get("result", "")),
        tokens={
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        },
        tool_calls=meta.get("num_turns", 0),
    )
    record.context_reads = list(meta.get("_reads", []))
    seq = 0
    for line in journey_log.read_text("utf-8").splitlines() if journey_log.is_file() else []:
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        kind = entry.get("kind")
        if kind == "exec":
            seq += 1
            outcome = ExecutionOutcome(
                ok=entry.get("ok", False), error=entry.get("error"),
                row_count=entry.get("row_count", 0), columns=entry.get("columns", []),
                rows=entry.get("rows", []), elapsed_ms=entry.get("elapsed_ms"),
            )
            record.drafts.append(Draft(seq=entry.get("seq", seq), system=entry["system"],
                                       request=entry["request"], complete=True,
                                       executed=True, outcome=outcome))
        elif kind == "discover":
            record.context_reads.append(f"discover:{entry.get('system')}")
        elif kind == "finish":
            record.declared_objects = list(entry.get("objects", []))
            if not record.notes:
                record.notes = entry.get("answer", "")
    _mark_final(record)
    return record
