"""QueryExecutor conformance for the postgres connector (capability §6).

These run against a real Postgres because the properties under test are
database properties: a parser can be mocked into agreeing with anything,
but `GRANT INSERT` either exists or it does not. Covers CC-3 (local
refusal with guardrails stripped), CC-4 (row cap + truncated), CC-5
(comment tag observed in the source's own statement log), the G3 role
wall including its startup refusal, and the staged-bypass path where a
write that got past a doctored validator still dies at the role.
"""

import base64
import datetime
import json
import os
import time

import psycopg
import pytest

from connectors.postgres.executor import (
    WRITE_PRIVILEGES,
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

-- CC-12: one row holding every mapping in the QE-5 table, so the
-- encoding is exercised type-by-type rather than by whatever types the
-- estate's own views happen to return.
CREATE VIEW public.v_types AS
SELECT date '2026-07-27'                             AS c_date,
       timestamp '2026-07-27 10:11:12.5'             AS c_timestamp,
       timestamptz '2026-07-27 10:11:12+02'          AS c_timestamptz,
       time '10:11:12'                               AS c_time,
       interval '1 day 02:03:04'                     AS c_interval,
       interval '-1 day -02:03:04'                   AS c_interval_neg,
       numeric '12345678901234567890.12345'          AS c_numeric,
       9007199254740993::bigint                      AS c_bigint_unsafe,
       42::bigint                                    AS c_bigint,
       1.5::float8                                   AS c_float,
       true                                          AS c_bool,
       uuid '11111111-2222-3333-4444-555555555555'   AS c_uuid,
       '\\xdeadbeef'::bytea                          AS c_bytea,
       '{"a": [1, 2], "b": null}'::jsonb             AS c_jsonb,
       '[10, 20]'::jsonb                             AS c_jsonb_array,
       ARRAY['a', 'b,c', NULL]::text[]               AS c_text_array,
       ARRAY[1, 2, 3]::int[]                         AS c_int_array,
       inet '192.168.0.1'                            AS c_inet,
       NULL::text                                    AS c_null;
GRANT SELECT ON public.v_types TO cl_exec;
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


# --- the shipped provisioning script ----------------------------------------


def test_deploy_execution_role_sql_provisions_a_role_that_cannot_write():
    """`deploy/execution-role.sql` is executable, tested SQL — not
    documentation that happens to look like SQL.

    It shipped once with a syntax error precisely because it had never
    been run, so this test runs the real file against a real Postgres and
    then verifies the two barriers *independently*:

      - the session default (`default_transaction_read_only`), which the
        role can switch off itself, and
      - the GRANTs, which it cannot.

    The second is the one G3 actually rests on, so the test defeats the
    first before asserting the second. A role that only fails writes
    because of a session setting would pass a naive check while leaving a
    write path one `SET` away.
    """
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "deploy" / "execution-role.sql"
    sql = script.read_text(encoding="utf-8").replace("<PASSWORD>", "provision-test-pw")

    with ephemeral_postgres(PG_IMAGE) as (_container, admin_dsn):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute("CREATE TABLE public.orders (id int, net numeric)")
            conn.execute("INSERT INTO public.orders VALUES (1, 10)")
            conn.execute(sql)  # the file, verbatim
            # A table created after provisioning: ALTER DEFAULT PRIVILEGES
            # must have made it readable without a second GRANT.
            conn.execute("CREATE TABLE public.created_later (id int)")
            conn.execute("INSERT INTO public.created_later VALUES (7)")

            # The file's own VERIFY block, as assertions.
            assert conn.execute(
                """SELECT 1 FROM information_schema.role_table_grants
                    WHERE grantee IN (SELECT rolname FROM pg_roles
                                       WHERE pg_has_role('example_exec', oid, 'USAGE'))
                      AND privilege_type = ANY(%s)""",
                (list(WRITE_PRIVILEGES),),
            ).fetchall() == []
            assert conn.execute(
                """SELECT 1 FROM pg_namespace
                    WHERE has_schema_privilege('example_exec', nspname, 'CREATE')
                      AND nspname NOT LIKE 'pg_%%' AND nspname <> 'information_schema'"""
            ).fetchall() == []
            assert conn.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls "
                "FROM pg_roles WHERE rolname = 'example_exec'"
            ).fetchone() == (False, False, False, False)

        exec_dsn = role_dsn(admin_dsn, "example_exec", "provision-test-pw")

        with psycopg.connect(exec_dsn, autocommit=True) as conn:
            assert conn.execute("SELECT count(*) FROM public.orders").fetchone() == (1,)
            assert conn.execute("SELECT count(*) FROM public.created_later").fetchone() == (1,)

            # Defeat the softer barrier, exactly as an attacker would.
            conn.execute("SET default_transaction_read_only = off")
            assert conn.execute("SHOW default_transaction_read_only").fetchone() == ("off",)

            for statement in [
                "INSERT INTO public.orders VALUES (2, 20)",
                "UPDATE public.orders SET net = 0",
                "DELETE FROM public.orders",
                "CREATE TABLE public.evil (id int)",
                "DROP TABLE public.orders",
                "CREATE SCHEMA sneaky",
            ]:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(statement)

            assert conn.execute("SELECT count(*) FROM public.orders").fetchone() == (1,)

        # And the executor's own startup check accepts what the file built.
        facts = PostgresExecutor().preflight(
            {"system": "demo", "mode": "live", "execute_dsn": exec_dsn}
        )
        assert facts["role"] == "example_exec"


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


# --- CC-12: QE-5 result value encoding --------------------------------------


def test_result_values_are_encoded_per_qe5(config):
    """CC-12: every row of the QE-5 table, against real Postgres types.

    Asserted on the executor's own output rather than on `to_json`, so a
    regression here cannot hide behind the boundary net in
    `ExecuteResult.to_json`.
    """
    result = PostgresExecutor().execute(
        config, sql_request("SELECT * FROM public.v_types"), Guardrails(), IDENTITY
    )
    row = dict(zip([c["name"] for c in result.columns], result.rows[0]))

    # temporal: ISO-8601 / RFC3339 text
    assert row["c_date"] == "2026-07-27"
    assert row["c_timestamp"] == "2026-07-27T10:11:12.500000"
    assert row["c_time"] == "10:11:12"
    stamped = datetime.datetime.fromisoformat(row["c_timestamptz"])
    assert stamped.utcoffset() is not None, "timestamptz must keep its offset"
    assert stamped == datetime.datetime(
        2026, 7, 27, 8, 11, 12, tzinfo=datetime.timezone.utc
    )
    # interval: the source's rendering, not Python's "1 day, 2:03:04"
    assert row["c_interval"] == "1 day 02:03:04"
    assert row["c_interval_neg"] == "-1 day -02:03:04"

    # numeric: string, at full precision — the fidelity rule
    assert row["c_numeric"] == "12345678901234567890.12345"
    assert isinstance(row["c_numeric"], str)

    # integers: native, until JSON's safe range runs out
    assert row["c_bigint"] == 42
    assert row["c_bigint_unsafe"] == "9007199254740993"

    assert row["c_float"] == 1.5
    assert row["c_bool"] is True
    assert row["c_uuid"] == "11111111-2222-3333-4444-555555555555"
    assert row["c_bytea"] == base64.b64encode(bytes.fromhex("deadbeef")).decode()

    # json/jsonb pass through as native JSON, arrays render as the source
    # writes them — including the quoting an embedded comma forces
    assert row["c_jsonb"] == {"a": [1, 2], "b": None}
    assert row["c_jsonb_array"] == [10, 20]
    assert row["c_text_array"] == '{a,"b,c",NULL}'
    assert row["c_int_array"] == "{1,2,3}"

    # no listed mapping: rendered, never dropped
    assert row["c_inet"] == "192.168.0.1"
    assert row["c_null"] is None

    # the whole point: the result survives the serializer that used to
    # take the runner down
    json.dumps(result.to_json())


def test_encoding_survives_the_delivery_boundary(config):
    """QE-5 is enforced at `to_json` too, so an executor that skipped it
    is still conformant. Encoding twice must not change the values."""
    result = PostgresExecutor().execute(
        config, sql_request("SELECT * FROM public.v_types"), Guardrails(), IDENTITY
    )
    assert result.to_json()["rows"] == result.rows
