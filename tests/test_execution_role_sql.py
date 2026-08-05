"""The shipped execution-role SQL actually runs, and produces a role
that passes our own G3 check (CP-6/M2).

This file exists because the first version of `deploy/execution-role.sql`
did not run at all: it contained
`GRANT CONNECT ON DATABASE current_database()`, which is a syntax error,
and it reached the operator anyway. Every other test in the M2 suite
provisions its roles with inline SQL written in the test, so the shipped
artifact — the one a human runs against the customer's production
database — was the single piece of the checkpoint nothing executed.

So: apply the real file to a real Postgres, then assert the role it
creates is exactly what the executor demands. A syntax error, a missing
REVOKE, or an over-broad GRANT fails here instead of in the Supabase SQL
editor.
"""

import re
from pathlib import Path

import psycopg
import pytest

from connectors.postgres.executor import (
    PostgresExecutor,
    RoleCheckFailed,
    check_role_is_readonly,
)
from connectors.postgres.ephemeral import docker_available, ephemeral_postgres
from connectors.sdk import ExecuteRequest, Guardrails, Identity

PG_IMAGE = "postgres:16"
ROLE_SQL = Path(__file__).resolve().parent.parent / "deploy" / "execution-role.sql"
TEST_PASSWORD = "role-sql-test-pw"

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not docker_available(), reason="Docker daemon unreachable"),
]


def apply_role_sql(container: str) -> None:
    """Run the shipped file through psql exactly as the operator does,
    with only the documented `<PASSWORD>` placeholder substituted."""
    import subprocess

    sql = ROLE_SQL.read_text(encoding="utf-8").replace("<PASSWORD>", TEST_PASSWORD)
    proc = subprocess.run(
        [
            "docker", "exec", "--interactive", container,
            "psql", "--username", "postgres", "--dbname", "postgres",
            "-v", "ON_ERROR_STOP=1", "--file", "-",
        ],
        input=sql.encode("utf-8"),
        capture_output=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        "deploy/execution-role.sql was rejected by postgres:\n"
        + proc.stderr.decode("utf-8", "replace")[-3000:]
    )


@pytest.fixture(scope="module")
def provisioned():
    with ephemeral_postgres(PG_IMAGE) as (container, admin_dsn):
        # Business data the role is meant to be able to read.
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(
                "CREATE TABLE public.orders (id int PRIMARY KEY, net numeric);"
                "INSERT INTO public.orders VALUES (1, 10), (2, 20);"
            )
        apply_role_sql(container)

        parsed = psycopg.conninfo.conninfo_to_dict(admin_dsn)
        parsed["user"] = "example_exec"
        parsed["password"] = TEST_PASSWORD
        yield {
            "container": container,
            "admin_dsn": admin_dsn,
            "exec_dsn": psycopg.conninfo.make_conninfo(**parsed),
        }


def test_the_shipped_file_runs_without_error(provisioned):
    """Covered by the fixture, asserted explicitly: the role exists."""
    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        row = conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'example_exec'"
        ).fetchone()
    assert row is not None and row[0] is True


def test_the_provisioned_role_passes_the_g3_check(provisioned):
    """The file and the executor's check agree — the point of both."""
    with psycopg.connect(provisioned["exec_dsn"]) as conn:
        facts = check_role_is_readonly(conn)
    assert facts["role"] == "example_exec"


def test_the_provisioned_role_can_read_business_data(provisioned):
    result = PostgresExecutor().execute(
        {"system": "pilot", "mode": "live", "execute_dsn": provisioned["exec_dsn"]},
        ExecuteRequest(dialect="sql", statement="SELECT id, net FROM public.orders ORDER BY id"),
        Guardrails(row_cap=10, timeout_s=10),
        Identity(subject="oidc|test"),
    )
    # `net` is numeric, so QE-5 hands it over as a string: a float would
    # silently change the fact (D-85). `id` is an int and stays native.
    assert result.rows == [[1, "10"], [2, "20"]]


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO public.orders VALUES (3, 30)",
        "UPDATE public.orders SET net = 0",
        "DELETE FROM public.orders",
        "DROP TABLE public.orders",
        "CREATE TABLE public.evil (id int)",
    ],
)
def test_the_provisioned_role_cannot_write(provisioned, statement):
    """Driven at the driver, past every parser we own: the grants the
    file hands out must make these impossible on their own."""
    with psycopg.connect(provisioned["exec_dsn"], autocommit=True) as conn:
        with pytest.raises(
            (psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)
        ):
            conn.execute(statement)


def test_write_still_refused_with_the_read_only_flag_switched_off(provisioned):
    """The file's own comment claims `default_transaction_read_only` is a
    convenience backstop and the GRANTs are the wall. Verify that claim
    rather than trusting it: turn the flag off, and writes must still
    fail on privileges alone."""
    with psycopg.connect(provisioned["exec_dsn"], autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO public.orders VALUES (4, 40)")


def test_role_session_defaults_are_set(provisioned):
    with psycopg.connect(provisioned["exec_dsn"]) as conn:
        settings = dict(
            conn.execute(
                "SELECT name, setting FROM pg_settings WHERE name IN "
                "('statement_timeout', 'idle_in_transaction_session_timeout', "
                "'default_transaction_read_only')"
            ).fetchall()
        )
    assert settings["default_transaction_read_only"] == "on"
    assert settings["statement_timeout"] == "60000"
    assert settings["idle_in_transaction_session_timeout"] == "60000"


def test_new_tables_from_the_provisioning_role_are_readable(provisioned):
    """The ALTER DEFAULT PRIVILEGES claim: a later migration by the same
    role does not silently make the agent blind."""
    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        conn.execute("CREATE TABLE public.added_later (id int); INSERT INTO public.added_later VALUES (7)")
    with psycopg.connect(provisioned["exec_dsn"], autocommit=True) as conn:
        assert conn.execute("SELECT id FROM public.added_later").fetchone()[0] == 7


def test_the_verify_queries_in_the_file_return_nothing(provisioned):
    """The file tells the operator these three checks should come back
    empty. Run the operator's own copy-paste and hold it to that."""
    sql = ROLE_SQL.read_text(encoding="utf-8")
    verify_block = sql.split("VERIFY", 1)[1]
    # Extract the two "expected: zero rows" queries as the operator sees
    # them (commented with a leading `--   `).
    queries = []
    for chunk in re.findall(r"((?:^--   .*\n)+)", verify_block, flags=re.M):
        text = "\n".join(line[5:] for line in chunk.strip("\n").splitlines())
        if text.strip().upper().startswith("SELECT"):
            queries.append(text.strip())
    write_grants, creatable, attributes = queries[0], queries[1], queries[2]

    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        assert conn.execute(write_grants).fetchall() == [], "role holds write grants"
        assert conn.execute(creatable).fetchall() == [], "role can create objects"
        assert conn.execute(attributes).fetchall() == [(False, False, False, False)]


def test_a_role_provisioned_without_the_file_is_still_refused(provisioned):
    """Control: the G3 check is not vacuously passing."""
    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        conn.execute(
            "DROP ROLE IF EXISTS sloppy_exec;"
            "CREATE ROLE sloppy_exec LOGIN PASSWORD 'p';"
            "GRANT USAGE ON SCHEMA public TO sloppy_exec;"
            "GRANT SELECT, INSERT ON public.orders TO sloppy_exec;"
        )
    parsed = psycopg.conninfo.conninfo_to_dict(provisioned["admin_dsn"])
    parsed["user"], parsed["password"] = "sloppy_exec", "p"
    with psycopg.connect(psycopg.conninfo.make_conninfo(**parsed)) as conn:
        with pytest.raises(RoleCheckFailed, match="write grants"):
            check_role_is_readonly(conn)
