"""The shipped introspection-role SQL actually runs, and produces a role
the connector accepts and cannot read data with (D-71.2, review #2 F3).

Same treatment as `test_execution_role_sql.py`, for the same reason
recorded in D-70: operator-run artifacts are code, and the convenience of
writing setup inline in a test is exactly what leaves the shipped file
uncovered. So the real file is applied through `psql`, and then the two
claims it makes about the role it creates are held to:

  1. it can introspect — the full catalog, byte-for-byte the same
     snapshot a superuser connection produces (the swap is safe);
  2. it cannot read a single row of business data — the property the
     `postgres` role it replaces did not have.

(1) is the interesting one. The file argues that shape-without-contents
works because `pg_catalog` is unfiltered by privilege; if that argument
is wrong, the snapshot differs and this test says so.
"""

import re

import psycopg
import pytest

from connectors.postgres.catalog import introspect_connection
from connectors.postgres.connector import check_introspection_role
from connectors.postgres.ephemeral import docker_available, ephemeral_postgres
from connectors.postgres.executor import RoleCheckFailed
from tests.conftest import INTROSPECTION_ROLE_SQL as ROLE_SQL, provision_introspection_role

PG_IMAGE = "postgres:16"
TEST_PASSWORD = "introspect-role-sql-test-pw"

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not docker_available(), reason="Docker daemon unreachable"),
]

# A schema with enough shape to make "the catalog answers the same"
# a claim with teeth: constraints, an FK, a view, an index, comments.
FIXTURE_DDL = """
CREATE TABLE public.customers (
    id    bigint PRIMARY KEY,
    email text NOT NULL UNIQUE,
    name  text
);
COMMENT ON TABLE public.customers IS 'people who buy things';
COMMENT ON COLUMN public.customers.email IS 'login identity';
CREATE TABLE public.orders (
    id          bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES public.customers (id),
    net         numeric(12,2) NOT NULL DEFAULT 0
);
CREATE INDEX orders_by_customer ON public.orders (customer_id);
CREATE VIEW public.v_totals AS
    SELECT customer_id, sum(net) AS total FROM public.orders GROUP BY customer_id;
INSERT INTO public.customers VALUES (1, 'a@example.com', 'A');
INSERT INTO public.orders VALUES (1, 1, 10);
"""


@pytest.fixture(scope="module")
def provisioned():
    """Applies the shipped file through psql, exactly as the operator
    does — the same helper the connector's live-mode fixtures use, so
    there is one way to provision this role and no test-only variant."""
    with ephemeral_postgres(PG_IMAGE) as (container, admin_dsn):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(FIXTURE_DDL)
        introspect_dsn = provision_introspection_role(container, admin_dsn, TEST_PASSWORD)
        yield {
            "container": container,
            "admin_dsn": admin_dsn,
            "introspect_dsn": introspect_dsn,
        }


def test_the_shipped_file_runs_without_error(provisioned):
    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        row = conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'contextlayer_introspect'"
        ).fetchone()
    assert row is not None and row[0] is True


def test_the_provisioned_role_passes_the_startup_check(provisioned):
    """The file and the connector's check agree — the point of both."""
    with psycopg.connect(provisioned["introspect_dsn"]) as conn:
        facts = check_introspection_role(conn)
    assert facts == {
        "role": "contextlayer_introspect",
        "superuser": False,
        "bypassrls": False,
    }


def test_introspection_is_byte_identical_to_the_superuser_connection(provisioned):
    """The swap's whole safety argument, executed.

    The exit criterion for the live swap is that the snapshot does not
    move on unchanged source state. That holds only if `pg_catalog`
    answers a least-privilege role exactly as it answers `postgres` —
    which this asserts directly, on the same database, moments apart.
    """
    with psycopg.connect(provisioned["admin_dsn"]) as conn:
        as_superuser = introspect_connection(conn, ["public"])
    with psycopg.connect(provisioned["introspect_dsn"]) as conn:
        as_introspector = introspect_connection(conn, ["public"])
    assert as_introspector == as_superuser
    # Not vacuous: the fixture really is in there.
    objects, _ = as_introspector
    assert {o["name"] for o in objects} == {"customers", "orders", "v_totals"}


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM public.customers",
        "SELECT * FROM public.orders",
        "SELECT * FROM public.v_totals",
        "SELECT count(*) FROM public.customers",
    ],
)
def test_the_provisioned_role_cannot_read_business_data(provisioned, statement):
    """The wall, driven at the driver. Introspection sees every table's
    shape and no table's contents — the asymmetry the file claims."""
    with psycopg.connect(provisioned["introspect_dsn"], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO public.customers VALUES (2, 'b@example.com', 'B')",
        "UPDATE public.customers SET name = 'x'",
        "DELETE FROM public.customers",
        "CREATE TABLE public.evil (id int)",
    ],
)
def test_the_provisioned_role_cannot_write(provisioned, statement):
    with psycopg.connect(provisioned["introspect_dsn"], autocommit=True) as conn:
        with pytest.raises(
            (psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)
        ):
            conn.execute(statement)


def test_role_session_defaults_are_set(provisioned):
    with psycopg.connect(provisioned["introspect_dsn"]) as conn:
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


def test_the_verify_queries_in_the_file_return_nothing(provisioned):
    """The file tells the operator these three checks should come back
    empty. Run the operator's own copy-paste and hold it to that."""
    sql = ROLE_SQL.read_text(encoding="utf-8")
    verify_block = sql.split("VERIFY", 1)[1]
    queries = []
    for chunk in re.findall(r"((?:^--   .*\n)+)", verify_block, flags=re.M):
        text = "\n".join(line[5:] for line in chunk.strip("\n").splitlines())
        if text.strip().upper().startswith("SELECT"):
            queries.append(text.strip())
    table_grants, creatable, attributes = queries[0], queries[1], queries[2]

    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        assert conn.execute(table_grants).fetchall() == [], "role holds table grants"
        assert conn.execute(creatable).fetchall() == [], "role can create objects"
        assert conn.execute(attributes).fetchall() == [(False, False, False, False)]


def test_a_superuser_connection_is_refused(provisioned):
    """Control: the check is not vacuously passing. This is the pilot's
    pre-F3 posture — `postgres`, holding everything — and it must now be
    refused rather than quietly introspected."""
    with psycopg.connect(provisioned["admin_dsn"]) as conn:
        with pytest.raises(RoleCheckFailed, match="SUPERUSER"):
            check_introspection_role(conn)


def test_a_bypassrls_role_is_refused(provisioned):
    """BYPASSRLS alone — no superuser — is the latent exposure F3 names,
    and is refused on its own."""
    with psycopg.connect(provisioned["admin_dsn"], autocommit=True) as conn:
        conn.execute(
            "DROP ROLE IF EXISTS sloppy_introspect;"
            "CREATE ROLE sloppy_introspect LOGIN PASSWORD 'p' BYPASSRLS;"
        )
    parsed = psycopg.conninfo.conninfo_to_dict(provisioned["admin_dsn"])
    parsed["user"], parsed["password"] = "sloppy_introspect", "p"
    with psycopg.connect(psycopg.conninfo.make_conninfo(**parsed)) as conn:
        with pytest.raises(RoleCheckFailed, match="BYPASSRLS"):
            check_introspection_role(conn)
