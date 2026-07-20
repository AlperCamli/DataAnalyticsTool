"""The Supabase/Postgres QueryExecutor (capability spec §6, CP-6/M2).

This is the direct-on-OLTP path the plan classes as the pilot-ending
risk, so the guardrails here are structural rather than advisory. Four
independent things must all hold before a row is returned, and none of
them trusts the caller, the gateway, or the payload:

1. **Role** (G3). Execution uses a dedicated DSN whose role is
   read-only *at the database level* — no INSERT/UPDATE/DELETE/DDL
   grants anywhere, not a superuser, distinct from the introspection
   role. `preflight` verifies this against the catalog at startup and
   refuses to serve execution otherwise. A parser is a filter; a role
   is a wall, and only the wall survives a bug in the filter.
2. **Statement class** (QE-1/CC-3). The same sqlglot refusal set the
   gateway ran is re-run here, from the shared `sqlval` entry point —
   so a payload with `guardrails` stripped, or a doctored gateway
   verdict, still cannot get a write past this frame.
3. **Session** (QE-1). Every query runs inside a `READ ONLY`
   transaction with `statement_timeout` set from the guardrail, per
   query, on the session — never a server default anyone can drift.
4. **Streaming cap** (QE-1/CI-7). Rows come off a server-side cursor
   in batches and stop at `row_cap + 1`; the cap is enforced *during*
   the fetch, so an over-cap result is bounded in memory rather than
   materialized and trimmed afterwards.

Config: `execute_dsn` / `execute_dsn_env` — deliberately distinct keys
from the introspection `dsn` / `dsn_env` (G3: same connector, two
roles, and pointing execution at the introspection role should be a
visible act, not a default). The role provisioning SQL and its runbook
step live in `deploy/execution-role.sql`.

Error messages carry SQLSTATE and the source's message, never the DSN
(JC-8) — libpq redacts passwords from its own errors, but a malformed
DSN raises before that and is never echoed.
"""

import os
import time

import psycopg
from psycopg import sql

from connectors.sdk import (
    AuthError,
    ConfigError,
    ExecuteRequest,
    ExecuteResult,
    Guardrails,
    GuardrailViolation,
    Identity,
    QueryExecutor,
    SourceUnavailable,
)
from sqlval import check_statement_class

# Schemas whose objects are Postgres' own; a read-only reporting role
# legitimately holds no grants here and we do not audit them for writes.
SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

# Any of these held on a user object means the role can mutate state.
WRITE_PRIVILEGES = ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

# Rows are pulled in batches off a server-side cursor so memory stays
# bounded by this, not by the result size (QE-1).
FETCH_BATCH = 500


class RoleCheckFailed(ConfigError):
    """The execution role can write — service is refused (G3).

    Non-retryable and loud on purpose: this is a provisioning error,
    and serving execution anyway is precisely the failure mode the
    check exists to prevent.
    """


def _connect(dsn: str, *, timeout_s: int) -> psycopg.Connection:
    try:
        return psycopg.connect(
            dsn,
            autocommit=True,
            application_name="contextlayer-execute",
            connect_timeout=max(1, min(timeout_s, 15)),
        )
    except psycopg.ProgrammingError as exc:
        raise ConfigError("invalid postgres execution DSN (not echoed; check the config)") from exc
    except psycopg.OperationalError as exc:
        message = str(exc)
        if "password" in message or "authentication" in message:
            raise AuthError(
                "postgres authentication failed for the execution role "
                "(check the read-only execution role credentials)"
            ) from exc
        raise SourceUnavailable(f"cannot reach postgres for execution: {message}") from exc


def execution_dsn(config: dict) -> str:
    """The execution DSN, kept separate from the introspection one (G3)."""
    if "execute_dsn" in config:
        return config["execute_dsn"]
    env_var = config.get("execute_dsn_env")
    if not env_var:
        raise ConfigError(
            "postgres execution requires config.execute_dsn or config.execute_dsn_env "
            "(a dedicated read-only role, distinct from the introspection DSN — see "
            "deploy/execution-role.sql)"
        )
    dsn = os.environ.get(env_var)
    if not dsn:
        raise ConfigError(f"environment variable {env_var!r} (config.execute_dsn_env) is unset or empty")
    return dsn


def check_role_is_readonly(conn: psycopg.Connection) -> dict:
    """Verify the connected role cannot write anything (G3).

    Checks role attributes and every table/schema privilege reachable
    through role membership. Returns the role facts on success; raises
    `RoleCheckFailed` naming the offending grant otherwise.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        row = cur.fetchone()
        if row is None:
            raise RoleCheckFailed("cannot read pg_roles for the current execution role")
        role, is_super, can_createdb, can_createrole, bypass_rls = row

        attributes = [
            ("SUPERUSER", is_super),
            ("CREATEDB", can_createdb),
            ("CREATEROLE", can_createrole),
            ("BYPASSRLS", bypass_rls),
        ]
        held = [name for name, value in attributes if value]
        if held:
            raise RoleCheckFailed(
                f"execution role {role!r} holds {', '.join(held)}; execution requires a role with "
                "none of these (G3). Refusing to serve execution."
            )

        # Table-level write grants, following role membership.
        cur.execute(
            """
            SELECT table_schema, table_name, privilege_type
              FROM information_schema.role_table_grants
             WHERE grantee IN (
                     SELECT rolname FROM pg_roles
                      WHERE pg_has_role(current_user, oid, 'USAGE'))
               AND table_schema <> ALL(%s)
               AND privilege_type = ANY(%s)
             ORDER BY table_schema, table_name, privilege_type
             LIMIT 5
            """,
            (list(SYSTEM_SCHEMAS), list(WRITE_PRIVILEGES)),
        )
        offending = cur.fetchall()
        if offending:
            shown = ", ".join(f"{p} on {s}.{t}" for s, t, p in offending)
            raise RoleCheckFailed(
                f"execution role {role!r} holds write grants ({shown}); execution requires a "
                "role with SELECT only (G3). Refusing to serve execution."
            )

        # Schema-level CREATE lets the role make objects it can then write.
        cur.execute(
            """
            SELECT nspname FROM pg_namespace
             WHERE nspname <> ALL(%s)
               AND nspname NOT LIKE 'pg_%%'
               AND has_schema_privilege(current_user, nspname, 'CREATE')
             ORDER BY nspname
             LIMIT 5
            """,
            (list(SYSTEM_SCHEMAS),),
        )
        creatable = [r[0] for r in cur.fetchall()]
        if creatable:
            raise RoleCheckFailed(
                f"execution role {role!r} holds CREATE on schema(s) {', '.join(creatable)}; "
                "execution requires a role that cannot create objects (G3). "
                "Refusing to serve execution."
            )

        cur.execute("SELECT current_setting('server_version')")
        version = cur.fetchone()[0]

    return {"role": role, "engine_version": version}


def _type_name(oid: int) -> str:
    try:
        info = psycopg.postgres.types.get(oid)
    except Exception:  # pragma: no cover - registry lookup is best-effort
        info = None
    return info.name if info is not None else f"oid:{oid}"


class PostgresExecutor(QueryExecutor):
    """SQL-dialect QueryExecutor for Supabase/Postgres."""

    def preflight(self, config: dict) -> dict:
        """Startup gate (G3): refuse to serve if the role can write."""
        dsn = execution_dsn(config)
        with _connect(dsn, timeout_s=10) as conn:
            return check_role_is_readonly(conn)

    def execute(
        self,
        config: dict,
        request: ExecuteRequest,
        guardrails: Guardrails,
        identity: Identity,
    ) -> ExecuteResult:
        if request.dialect != "sql":
            raise ConfigError(
                f"postgres executes the sql dialect, got {request.dialect!r}"
            )
        statement = request.statement
        if not isinstance(statement, str) or not statement.strip():
            raise ConfigError("request.statement (non-empty string) required")

        # (2) Local statement-class enforcement — independent of the
        # gateway having done it, and of guardrails being present at all
        # (QE-1/CC-3). Same refusal set, one implementation.
        _, findings = check_statement_class(statement, engine="postgres")
        if findings:
            first = findings[0]
            raise GuardrailViolation(
                f"statement refused by the executor's local check: {first['message']}",
                capability_code="statement_class",
                detail={"findings": findings},
            )

        dsn = execution_dsn(config)
        tagged = f"{identity.comment_tag()}\n{statement}"
        started = time.monotonic()

        with _connect(dsn, timeout_s=guardrails.timeout_s) as conn:
            # (1) The role wall is re-verified per execution, not only at
            # startup: grants can change under a long-lived runner, and
            # this is the check that must not be stale.
            role_facts = check_role_is_readonly(conn)
            try:
                conn.autocommit = False
                conn.read_only = True  # (3) READ ONLY transaction
                with conn.cursor() as setup:
                    setup.execute(
                        sql.SQL("SET LOCAL statement_timeout = {}").format(
                            sql.Literal(guardrails.timeout_s * 1000)
                        )
                    )
                    # Belt and braces: even inside a READ ONLY transaction,
                    # pin the session's own read-only flag for this unit.
                    setup.execute("SET LOCAL default_transaction_read_only = on")

                columns, rows, truncated = self._stream(
                    conn, tagged, request.params, guardrails.row_cap
                )
                conn.rollback()  # read-only: nothing to commit
            except psycopg.errors.QueryCanceled as exc:
                conn.rollback()
                raise GuardrailViolation(
                    f"query exceeded the {guardrails.timeout_s}s statement timeout",
                    capability_code="timeout",
                    detail={"timeout_s": guardrails.timeout_s},
                ) from exc
            except psycopg.errors.InsufficientPrivilege as exc:
                conn.rollback()
                # The role wall doing its job — a statement that passed a
                # doctored validator dies here (staged-bypass path).
                raise GuardrailViolation(
                    f"the execution role is not permitted to run this statement: {exc}",
                    capability_code="permission_denied_at_source",
                ) from exc
            except psycopg.errors.ReadOnlySqlTransaction as exc:
                conn.rollback()
                raise GuardrailViolation(
                    f"write attempted on the read-only execution surface: {exc}",
                    capability_code="permission_denied_at_source",
                ) from exc
            except (
                psycopg.errors.UndefinedTable,
                psycopg.errors.UndefinedColumn,
                psycopg.errors.UndefinedFunction,
            ) as exc:
                conn.rollback()
                # The validate/execute race (capability §6): the statement
                # validated against a snapshot the live schema has moved
                # past. Deterministic fault-ledger input.
                raise GuardrailViolation(
                    f"statement references an object the live schema lacks: {exc}",
                    capability_code="schema_mismatch",
                    detail={"validated_against": guardrails.validated_against},
                ) from exc
            except psycopg.errors.SyntaxError as exc:
                conn.rollback()
                raise GuardrailViolation(
                    f"postgres rejected the statement: {exc}",
                    capability_code="syntax_error",
                ) from exc
            except psycopg.OperationalError as exc:
                raise SourceUnavailable(f"lost postgres connection mid-execution: {exc}") from exc

        return ExecuteResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=int((time.monotonic() - started) * 1000),
            source={
                "executed_on": "primary",
                "engine_version": role_facts["engine_version"],
                "role": role_facts["role"],
            },
        )

    @staticmethod
    def _stream(
        conn: psycopg.Connection,
        statement: str,
        params: tuple,
        row_cap: int,
    ) -> tuple[list[dict], list[list], bool]:
        """Fetch at most `row_cap + 1` rows off a server-side cursor.

        The extra row is how truncation is *detected* without pulling
        the rest: if it arrives, the cap was hit, and it is dropped
        rather than returned (CI-7 — `truncated` is the explicit fact).
        """
        # A named cursor keeps the result set server-side; without it
        # psycopg buffers the whole thing before we see row one, which
        # would make the cap post-hoc and the memory unbounded.
        with conn.cursor(name="cl_execute") as cur:
            cur.itersize = FETCH_BATCH
            # QE-3: parameters are bound by the driver, never interpolated.
            cur.execute(statement, params or None)

            columns = [
                {"name": desc.name, "type": _type_name(desc.type_code)}
                for desc in (cur.description or [])
            ]
            rows: list[list] = []
            truncated = False
            while len(rows) <= row_cap:
                batch = cur.fetchmany(min(FETCH_BATCH, row_cap + 1 - len(rows)))
                if not batch:
                    break
                for record in batch:
                    if len(rows) >= row_cap:
                        truncated = True
                        break
                    rows.append(list(record))
                if truncated:
                    break
        return columns, rows, truncated
