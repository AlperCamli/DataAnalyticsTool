"""Guardrailed local executors (R3) — the only tools the journey agent runs.

Execution access is identical across all three conditions; only context
access differs. Every executor is guardrailed:

- **SQL** — SELECT-only (enforced at parse time *and* by a read-only
  transaction), a 30-second ``statement_timeout``, and a 10,000-row cap.
- **GA4 / GSC** — one ``runReport`` / ``searchanalytics.query`` per call,
  reusing the connectors' service-account auth (``_credentials``); no
  write surface exists.

The runner depends on the ``Executor`` protocol, so tests inject a
``ScriptedExecutor`` and spend nothing. ``LiveExecutor`` is the env-gated
real path used by the baseline run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

ROW_CAP = 10_000
STATEMENT_TIMEOUT_MS = 30_000

# DML/DDL node types that must never appear, even nested in a CTE.
_FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Drop, exp.Create,
    exp.Alter, exp.TruncateTable, exp.Grant,
)


class ExecutionError(Exception):
    """A guard rejection or an execution failure (message is credential-safe)."""


class SqlGuardError(ExecutionError):
    """A statement the SELECT-only guard refuses to run."""


@dataclass
class ExecResult:
    ok: bool
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None
    elapsed_ms: float | None = None


def assert_select_only(statement: str) -> exp.Expression:
    """Return the single SELECT to run, or raise SqlGuardError.

    Allows a leading ``SET statement_timeout`` (the guard sets its own,
    but the goldens carry one) and exactly one read query
    (SELECT / WITH / UNION). Any DML/DDL — including embedded in a CTE — is
    refused; the read-only transaction in ``LiveExecutor`` is the second
    line of defence.
    """
    try:
        parsed = [s for s in sqlglot.parse(statement, read="postgres") if s is not None]
    except ParseError as exc:
        raise SqlGuardError(f"unparseable SQL: {exc}") from exc

    select: exp.Expression | None = None
    for stmt in parsed:
        for node in stmt.walk():
            if isinstance(node, _FORBIDDEN):
                raise SqlGuardError(f"non-SELECT statement refused: {type(node).__name__}")
        if isinstance(stmt, (exp.Select, exp.Union, exp.Subquery)):
            if select is not None:
                raise SqlGuardError("more than one query statement in one call")
            select = stmt
        elif isinstance(stmt, (exp.Set, exp.Command)):
            text = stmt.sql(dialect="postgres").strip().upper()
            if not text.startswith("SET STATEMENT_TIMEOUT") and not text.startswith(
                "SET LOCAL STATEMENT_TIMEOUT"
            ):
                raise SqlGuardError(f"only SET statement_timeout is allowed, got: {text[:40]}")
        else:
            raise SqlGuardError(f"statement type not permitted: {type(stmt).__name__}")
    if select is None:
        raise SqlGuardError("no SELECT statement found")
    return select


class Executor(Protocol):
    def run_sql(self, system: str, statement: str) -> ExecResult: ...
    def run_api(self, system: str, operation: str, property: str, body: Mapping[str, Any]) -> ExecResult: ...


# --------------------------------------------------------------------------
# scripted executor (tests / dry runs — zero live access)


class ScriptedExecutor:
    """Returns canned results keyed by system; records the calls made."""

    def __init__(self, responses: Mapping[str, ExecResult] | None = None, *, default_ok: bool = True):
        self._responses = dict(responses or {})
        self._default_ok = default_ok
        self.calls: list[dict[str, Any]] = []

    def _lookup(self, system: str, kind: str) -> ExecResult:
        for key in (f"{system}:{kind}", system):
            if key in self._responses:
                return self._responses[key]
        if self._default_ok:
            return ExecResult(ok=True, columns=["c"], rows=[[1]], row_count=1)
        return ExecResult(ok=False, error="scripted failure")

    def run_sql(self, system: str, statement: str) -> ExecResult:
        self.calls.append({"system": system, "kind": "sql", "statement": statement})
        assert_select_only(statement)  # guard runs even in tests
        return self._lookup(system, "sql")

    def run_api(self, system, operation, property, body) -> ExecResult:
        self.calls.append({"system": system, "kind": "api", "operation": operation,
                           "property": property, "body": dict(body)})
        return self._lookup(system, "api")


# --------------------------------------------------------------------------
# live executor (env-gated — the baseline run)


class LiveExecutor:
    """Real guardrailed execution against the customer estate.

    Built with the per-system connection config (Supabase DSN, GA4/GSC
    service-account config). SQL runs in a read-only transaction with a
    30s ``statement_timeout``; API calls reuse the connectors' credentials.
    """

    DATA_API = "https://analyticsdata.googleapis.com"
    GSC_API = "https://www.googleapis.com/webmasters/v3"

    def __init__(self, *, supabase_dsn: str | None = None,
                 ga4_config: Mapping[str, Any] | None = None,
                 gsc_config: Mapping[str, Any] | None = None):
        self._dsn = supabase_dsn
        self._ga4_config = ga4_config
        self._gsc_config = gsc_config
        self._sessions: dict[str, Any] = {}

    def run_sql(self, system: str, statement: str) -> ExecResult:
        import time as _time
        import psycopg

        select = assert_select_only(statement)
        if self._dsn is None:
            return ExecResult(ok=False, error="no Supabase DSN configured")
        query = select.sql(dialect="postgres")
        start = _time.monotonic()
        try:
            with psycopg.connect(self._dsn, autocommit=False) as conn:
                conn.read_only = True  # hard write guard (defense in depth)
                with conn.cursor() as cur:
                    cur.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
                    cur.execute(query)
                    columns = [d.name for d in cur.description] if cur.description else []
                    fetched = cur.fetchmany(ROW_CAP + 1)
                    truncated = len(fetched) > ROW_CAP
                    rows = [list(r) for r in fetched[:ROW_CAP]]
            return ExecResult(ok=True, columns=columns, rows=rows, row_count=len(rows),
                              truncated=truncated, elapsed_ms=(_time.monotonic() - start) * 1000)
        except psycopg.Error as exc:
            # psycopg errors can carry the query; surface only the SQLSTATE + type.
            code = getattr(getattr(exc, "diag", None), "sqlstate", None)
            return ExecResult(ok=False, error=f"sql error ({type(exc).__name__}{f' {code}' if code else ''})",
                              elapsed_ms=(_time.monotonic() - start) * 1000)

    def _session(self, system: str):
        if system not in self._sessions:
            from google.auth.transport.requests import AuthorizedSession
            if system == "ga4":
                from connectors.ga4.connector import _credentials
                cfg = self._ga4_config
            else:
                from connectors.gsc.connector import _credentials
                cfg = self._gsc_config
            if cfg is None:
                raise ExecutionError(f"no {system} config provided")
            self._sessions[system] = AuthorizedSession(_credentials(dict(cfg)))
        return self._sessions[system]

    def run_api(self, system, operation, property, body) -> ExecResult:
        import time as _time
        start = _time.monotonic()
        try:
            if system == "ga4":
                url = f"{self.DATA_API}/v1beta/{property}:runReport"
                resp = self._session("ga4").post(url, json=dict(body), timeout=60)
                payload = resp.json() if resp.content else {}
                if resp.status_code >= 400:
                    return ExecResult(ok=False, error=f"ga4 api {resp.status_code}")
                return _ga4_result(payload, (_time.monotonic() - start) * 1000)
            if system == "gsc":
                url = f"{self.GSC_API}/sites/{property}/searchAnalytics/query"
                resp = self._session("gsc").post(url, json=dict(body), timeout=60)
                payload = resp.json() if resp.content else {}
                if resp.status_code >= 400:
                    return ExecResult(ok=False, error=f"gsc api {resp.status_code}")
                return _gsc_result(dict(body), payload, (_time.monotonic() - start) * 1000)
            return ExecResult(ok=False, error=f"unknown api system {system!r}")
        except ExecutionError as exc:
            return ExecResult(ok=False, error=str(exc))
        except Exception as exc:  # network/JSON — credential-safe message
            return ExecResult(ok=False, error=f"{system} api call failed ({type(exc).__name__})")


def _ga4_result(payload: Mapping[str, Any], elapsed_ms: float) -> ExecResult:
    dims = [h["name"] for h in payload.get("dimensionHeaders", [])]
    mets = [h["name"] for h in payload.get("metricHeaders", [])]
    columns = dims + mets
    rows = []
    for row in payload.get("rows", []):
        dv = [d.get("value") for d in row.get("dimensionValues", [])]
        mv = [m.get("value") for m in row.get("metricValues", [])]
        rows.append(dv + mv)
    return ExecResult(ok=True, columns=columns, rows=rows, row_count=len(rows), elapsed_ms=elapsed_ms)


def _gsc_result(body: Mapping[str, Any], payload: Mapping[str, Any], elapsed_ms: float) -> ExecResult:
    dims = list(body.get("dimensions", []) or [])
    columns = dims + ["clicks", "impressions", "ctr", "position"]
    rows = []
    for row in payload.get("rows", []):
        keys = list(row.get("keys", []))
        rows.append(keys + [row.get("clicks"), row.get("impressions"),
                            row.get("ctr"), row.get("position")])
    return ExecResult(ok=True, columns=columns, rows=rows, row_count=len(rows), elapsed_ms=elapsed_ms)
