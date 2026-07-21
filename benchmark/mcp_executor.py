"""Local MCP executor server for Backend B (headless Claude Code).

Exposes the guardrailed executors (R3) as MCP tools so a `claude -p`
journey can execute without a Bash tool and without ever seeing the
credentials — those are read from this process's environment only
(``.mcp.json`` injects them into this server's env, not the agent's).

Every call is appended, in full, to the per-journey log at
``$BENCHMARK_JOURNEY_LOG`` — that log (not the CLI transcript) is the
authoritative source of drafts, execution outcomes (columns/rows for
correctness scoring), context reads, and the declared object set. The
runner merges it with the CLI JSON (cost/usage) into a ``JourneyRecord``.

Env contract:
  BENCHMARK_JOURNEY_LOG   - JSONL file this server appends to (required)
  BENCHMARK_SNAPSHOTS_DIR - pinned snapshots, for discover_schema
  BENCHMARK_SUPABASE_DSN  - read-only DSN for run_sql
  BENCHMARK_GA4_CONFIG    - path to the GA4 connector config (service acct)
  BENCHMARK_GSC_CONFIG    - path to the GSC connector config
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from benchmark.executors import ExecResult, ExecutionError, LiveExecutor
from benchmark.runner import snapshot_discovery

_LOG_LOCK = threading.Lock()
_SEQ = 0


def _log(entry: dict[str, Any]) -> None:
    path = os.environ.get("BENCHMARK_JOURNEY_LOG")
    if not path:
        return
    with _LOG_LOCK:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")


def _load_snapshots() -> list[dict]:
    d = os.environ.get("BENCHMARK_SNAPSHOTS_DIR")
    if not d:
        return []
    return [json.loads(p.read_text("utf-8")) for p in sorted(Path(d).glob("*.json"))]


def _load_config(env_var: str) -> dict | None:
    path = os.environ.get(env_var)
    if not path or not Path(path).is_file():
        return None
    return json.loads(Path(path).read_text("utf-8"))


_SNAPSHOTS = _load_snapshots()
_EXECUTOR = LiveExecutor(
    supabase_dsn=os.environ.get("BENCHMARK_SUPABASE_DSN"),
    ga4_config=_load_config("BENCHMARK_GA4_CONFIG"),
    gsc_config=_load_config("BENCHMARK_GSC_CONFIG"),
)

mcp = FastMCP("executor")


def _record_exec(system: str, request: dict, res: ExecResult) -> dict:
    global _SEQ
    _SEQ += 1
    _log({
        "kind": "exec", "seq": _SEQ, "system": system, "request": request,
        "ok": res.ok, "error": res.error, "columns": res.columns, "rows": res.rows,
        "row_count": res.row_count, "truncated": res.truncated, "elapsed_ms": res.elapsed_ms,
    })
    if res.ok:
        return {"ok": True, "columns": res.columns, "row_count": res.row_count,
                "rows": res.rows[:50], "truncated": res.truncated}
    return {"ok": False, "error": res.error}


@mcp.tool()
def run_sql(statement: str) -> dict:
    """Run one SELECT-only Postgres query (30s timeout, 10k row cap). Qualify tables."""
    request = {"dialect": "sql", "statement": statement}
    try:
        res = _EXECUTOR.run_sql("supabase", statement)
    except ExecutionError as exc:
        res = ExecResult(ok=False, error=str(exc))
    return _record_exec("supabase", request, res)


@mcp.tool()
def run_ga4_report(property: str, body: dict) -> dict:
    """Run one GA4 runReport. Name dimensions/metrics exactly as the property defines them."""
    request = {"dialect": "api", "operation": "runReport", "property": property, "body": body}
    try:
        res = _EXECUTOR.run_api("ga4", "runReport", property, body)
    except ExecutionError as exc:
        res = ExecResult(ok=False, error=str(exc))
    return _record_exec("ga4", request, res)


@mcp.tool()
def run_gsc_query(property: str, body: dict) -> dict:
    """Run one Search Console searchanalytics.query (returns clicks/impressions/ctr/position)."""
    request = {"dialect": "api", "operation": "searchanalytics.query", "property": property, "body": body}
    try:
        res = _EXECUTOR.run_api("gsc", "searchanalytics.query", property, body)
    except ExecutionError as exc:
        res = ExecResult(ok=False, error=str(exc))
    return _record_exec("gsc", request, res)


@mcp.tool()
def list_context() -> dict:
    """List the knowledge-base documents available to read (kb conditions)."""
    root = os.environ.get("BENCHMARK_CONTEXT_ROOT")
    _log({"kind": "list_context"})
    if not root or not Path(root).is_dir():
        return {"documents": []}
    base = Path(root)
    docs = sorted(
        str(p) for p in base.rglob("*")
        if p.is_file() and not p.name.startswith(".") and "/.git/" not in p.as_posix()
    )
    return {"root": str(base), "documents": docs}


@mcp.tool()
def discover_schema(system: str) -> str:
    """Introspect a system's live structure (tables/columns for SQL, dimensions/metrics for API)."""
    _log({"kind": "discover", "system": system})
    return snapshot_discovery(_SNAPSHOTS, system)


@mcp.tool()
def finish(objects: list[str], answer: str) -> str:
    """Finalize: declare the fully-qualified object ids your final query used, and the answer."""
    _log({"kind": "finish", "objects": objects, "answer": answer})
    return "recorded"


if __name__ == "__main__":
    mcp.run()
