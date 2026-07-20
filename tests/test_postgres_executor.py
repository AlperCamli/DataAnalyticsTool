"""QueryExecutor conformance for the postgres connector (capability §6).

These run against a real Postgres because the properties under test are
database properties: a parser can be mocked into agreeing with anything,
but `GRANT INSERT` either exists or it does not. Covers CC-3 (local
refusal with guardrails stripped), CC-4 (row cap + truncated), CC-5
(comment tag observed in the source's own statement log), the G3 role
wall including its startup refusal, and the staged-bypass path where a
write that got past a doctored validator still dies at the role.
"""

import os
import time

import psycopg
import pytest

from connectors.postgres.executor import (
    PostgresExecutor,
    RoleCheckFailed,
    check_role_is_readonly,
)
from connectors.postgres.ephemeral import docker_available, ephemeral_postgres
from connectors.sdk import (
    ConfigError,
    ExecuteRequest,
    Guardrails,
    GuardrailViolation,
    Identity,
)
from connectors.sdk.runner import Job, run_job

PG_IMAGE = os.environ.get("CTXLAYER_PG_TEST_IMAGE", "postgres:16")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not docker_available(), reason="Docker daemon unreachable"),
]

SEED_SQL = """
CREATE TABLE public.orders (
    id      serial PRIMARY KEY,
    region  text NOT NULL,
    net     numeric(12,2) NOT NULL
);
INSERT INTO public.orders (region, net)
SELECT (ARRAY['EMEA','AMER','APAC'])[1 + (i % 3)], (i * 10)::numeric
  FROM generate_series(1, 500) AS i;

-- The reporting role: SELECT only, no CREATE anywhere (G3).
CREATE ROLE cl_exec LOGIN PASSWORD 'exec-pw';
GRANT USAGE ON SCHEMA public TO cl_exec;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cl_exec;
REVOKE CREATE ON SCHEMA public FROM cl_exec;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- A deliberately over-granted role, to prove the startup check refuses.
CREATE ROLE cl_writer LOGIN PASSWORD 'writer-pw';
GRANT USAGE ON SCHEMA public TO cl_writer;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO cl_writer;
"""


def role_dsn(admin_dsn: str, role: str, password: str) -> str:
    """Rewrite an admin DSN to connect as `role`."""
    parsed = psycopg.conninfo.conninfo_to_dict(admin_dsn)
    parsed["user"] = role
    parsed["password"] = password
    return psycopg.conninfo.make_conninfo(**parsed)


@pytest.fixture(scope="module")
def estate():
    """One container per module: seeded data plus the two roles."""
    with ephemeral_postgres(PG_IMAGE) as (container, admin_dsn):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(SEED_SQL)
        yield {
            "container": container,
            "admin_dsn": admin_dsn,
            "exec_dsn": role_dsn(admin_dsn, "cl_exec", "exec-pw"),
            "writer_dsn": role_dsn(admin_dsn, "cl_writer", "writer-pw"),
        }


@pytest.fixture
def config(estate):
    return {"system": "demo", "mode": "live", "execute_dsn": estate["exec_dsn"]}


def sql_request(statement, params=()):
    return ExecuteRequest(dialect="sql", statement=statement, params=tuple(params))


IDENTITY = Identity(
    subject="oidc|a.demir@customer.example",
    roles=("sales",),
    session_id="s-test",
    intent="net sales by region",
)


# --- G3: the role wall ------------------------------------------------------


def test_startup_check_passes_for_a_readonly_role(config):
    facts = PostgresExecutor().preflight(config)
    assert facts["role"] == "cl_exec"


def test_startup_check_refuses_a_role_with_write_grants(estate):
    """G3 exit criterion: point execution at a writable role and the
    server refuses to serve execution, saying which grant is the
    problem."""
    config = {"system": "demo", "mode": "live", "execute_dsn": estate["writer_dsn"]}
    with pytest.raises(RoleCheckFailed) as excinfo:
        PostgresExecutor().preflight(config)
    message = str(excinfo.value)
    assert "write grants" in message
    assert "INSERT on public.orders" in message
    assert "Refusing to serve execution" in message


def test_startup_check_refuses_a_superuser(estate):
    """The admin DSN is a superuser — grants are irrelevant, it is
    refused on role attributes alone."""
    config = {"system": "demo", "mode": "live", "execute_dsn": estate["admin_dsn"]}
    with pytest.raises(RoleCheckFailed) as excinfo:
        PostgresExecutor().preflight(config)
    assert "SUPERUSER" in str(excinfo.value)


def test_execution_dsn_must_be_configured_explicitly():
    """G3: execution never silently falls back to the introspection DSN."""
    with pytest.raises(ConfigError) as excinfo:
        PostgresExecutor().execute(
            {"system": "demo", "mode": "live", "dsn": "postgresql://x/y"},
            sql_request("SELECT 1"),
            Guardrails(),
            IDENTITY,
        )
    assert "execute_dsn" in str(excinfo.value)


# --- happy path -------------------------------------------------------------


def test_executes_a_select_and_shapes_the_result(config):
    result = PostgresExecutor().execute(
        config,
        sql_request("SELECT region, sum(net) AS net_total FROM public.orders GROUP BY region ORDER BY region"),
        Guardrails(row_cap=100, timeout_s=30),
        IDENTITY,
    )
    assert [c["name"] for c in result.columns] == ["region", "net_total"]
    assert [row[0] for row in result.rows] == ["AMER", "APAC", "EMEA"]
    assert result.row_count == 3
    assert result.truncated is False
    assert result.source["executed_on"] == "primary"
    assert result.source["role"] == "cl_exec"


def test_parameters_are_bound_not_interpolated(config):
    """QE-3. The param is a string that would be a syntax error if it
    were ever spliced into the statement text."""
    result = PostgresExecutor().execute(
        config,
        sql_request("SELECT count(*) FROM public.orders WHERE region = %s", ["EMEA'; DROP TABLE public.orders; --"]),
        Guardrails(),
        IDENTITY,
    )
    assert result.rows == [[0]]
    # The table is still there.
    after = PostgresExecutor().execute(
        config, sql_request("SELECT count(*) FROM public.orders"), Guardrails(), IDENTITY
    )
    assert after.rows == [[500]]


# --- CC-4 / CI-7: the row cap ----------------------------------------------


def test_row_cap_truncates_during_streaming(config):
    """CC-4: rows ≤ cap, `truncated` true, and the cap is applied while
    fetching — the 500-row source never lands in memory whole."""
    result = PostgresExecutor().execute(
        config,
        sql_request("SELECT id FROM public.orders ORDER BY id"),
        Guardrails(row_cap=10),
        IDENTITY,
    )
    assert len(result.rows) == 10
    assert result.row_count == 10
    assert result.truncated is True
    assert [r[0] for r in result.rows] == list(range(1, 11))


def test_result_at_exactly_the_cap_is_not_flagged_truncated(config):
    result = PostgresExecutor().execute(
        config,
        sql_request("SELECT id FROM public.orders ORDER BY id LIMIT 10"),
        Guardrails(row_cap=10),
        IDENTITY,
    )
    assert len(result.rows) == 10
    assert result.truncated is False


# --- CC-3: local enforcement with guardrails stripped -----------------------

CANARY_WRITES = [
    "INSERT INTO public.orders (region, net) VALUES ('X', 1)",
    "UPDATE public.orders SET net = 0",
    "DELETE FROM public.orders",
    "DROP TABLE public.orders",
    "CREATE TABLE public.evil (id int)",
    "TRUNCATE public.orders",
    # CTE-wrapped write — the shape that reads as a SELECT at a glance.
    "WITH w AS (INSERT INTO public.orders (region, net) VALUES ('X', 1) RETURNING id) SELECT * FROM w",
    # Multi-statement smuggling.
    "SELECT 1; DROP TABLE public.orders",
    # Locking clause on the read surface.
    "SELECT * FROM public.orders FOR UPDATE",
]


@pytest.mark.parametrize("statement", CANARY_WRITES)
def test_canary_writes_refused_locally_with_no_guardrails_in_payload(config, statement):
    """CC-3: the payload carries no guardrails at all — a malicious or
    buggy gateway — and the executor still refuses."""
    job = Job(
        job_id="j-cc3",
        config=config,
        type="execute",
        request={"dialect": "sql", "statement": statement},
        guardrails=None,  # stripped
        identity={"subject": "oidc|attacker"},
    )
    # The shipped connector, not a stand-in: the point is that the real
    # assembly refuses, end to end through the engine.
    from connectors.postgres.connector import connector

    outcome = run_job(connector, job)
    assert outcome.status == "failed"
    assert outcome.error.code == "guardrail"
    assert outcome.error.detail["capability_code"] == "statement_class"


def test_row_survives_every_canary(config):
    """After the CC-3 sweep, the estate is untouched."""
    result = PostgresExecutor().execute(
        config, sql_request("SELECT count(*) FROM public.orders"), Guardrails(), IDENTITY
    )
    assert result.rows == [[500]]


# --- staged bypass: the role wall behind the parser -------------------------


def test_write_that_passed_a_doctored_validator_dies_at_the_db_role(config):
    """The staged-bypass test. We deliberately go around the executor's
    own parser check — simulating a validator that was compromised or
    bypassed — and call the driver exactly as the executor would, inside
    the same READ ONLY transaction under the same role. The write must
    still be impossible.

    This is the test that justifies G3: it is the only layer left when
    every parser in the stack has been defeated.
    """
    dsn = config["execute_dsn"]
    with psycopg.connect(dsn, autocommit=False) as conn:
        conn.read_only = True
        with pytest.raises(
            (psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)
        ):
            conn.execute("INSERT INTO public.orders (region, net) VALUES ('EVIL', 1)")
        conn.rollback()

    # And with the read-only transaction ALSO removed, the grant alone holds.
    with psycopg.connect(dsn, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO public.orders (region, net) VALUES ('EVIL', 1)")

    with psycopg.connect(dsn, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM public.orders").fetchone()[0] == 500


# --- guardrail terminations -------------------------------------------------


def test_statement_timeout_is_enforced_per_query(config):
    """QE-1: the timeout is set on the session per query, so a slow
    statement terminates as a `timeout` guardrail rather than hanging
    the waiting caller."""
    started = time.monotonic()
    with pytest.raises(GuardrailViolation) as excinfo:
        PostgresExecutor().execute(
            config,
            sql_request("SELECT count(*) FROM generate_series(1, 200000000)"),
            Guardrails(timeout_s=1),
            IDENTITY,
        )
    assert excinfo.value.capability_code == "timeout"
    assert time.monotonic() - started < 20  # terminated, not hung


def test_missing_object_surfaces_as_schema_mismatch(config):
    """The validate/execute race (capability §6): validated against a
    snapshot the live schema has moved past."""
    with pytest.raises(GuardrailViolation) as excinfo:
        PostgresExecutor().execute(
            config,
            sql_request("SELECT * FROM public.dropped_yesterday"),
            Guardrails(validated_against="sha256:stale"),
            IDENTITY,
        )
    assert excinfo.value.capability_code == "schema_mismatch"
    assert excinfo.value.detail["validated_against"] == "sha256:stale"


# --- CC-5: comment tagging --------------------------------------------------


def test_comment_tag_is_observable_in_the_source_statement_log(estate, config):
    """CC-5: QE-2's tag is verified where it matters — in Postgres' own
    view of the statement, not in our string building."""
    with psycopg.connect(estate["admin_dsn"], autocommit=True) as admin:
        admin.execute("ALTER SYSTEM SET log_statement = 'all'")
        admin.execute("SELECT pg_reload_conf()")

    PostgresExecutor().execute(
        config,
        sql_request("SELECT 42 AS answer"),
        Guardrails(),
        IDENTITY,
    )

    import subprocess

    logs = subprocess.run(
        ["docker", "logs", estate["container"]],
        capture_output=True, text=True, timeout=60,
    )
    combined = logs.stdout + logs.stderr
    assert "/* contextlayer user=oidc|a.demir@customer.example" in combined
    assert "session=s-test" in combined
    # QE-2: the intent text itself never rides the wire — only its hash.
    assert "net sales by region" not in combined
