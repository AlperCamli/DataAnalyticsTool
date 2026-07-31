"""Container-backed conformance for the postgres connector (spec §9).

C-2 (S-3) and C-3 (S-4) — the task 1.2 exit criteria — run for real
here: two fresh ddl-file runs must be byte-identical, and the same DDL
introspected via ddl-file mode and via live mode must produce identical
canonical bodies. C-5/C-6 are staged with COMMENT ON / ALTER TABLE on a
scratch container. C-7's transport half (failed job → nothing emitted →
dead-letter) is test_sdk_runner's; the connector-level failure paths
live in test_postgres_config.py plus the bad-DDL test below.

Marker `postgres`: needs a reachable Docker daemon; skipped otherwise.
Override the image with CTXLAYER_PG_TEST_IMAGE (default postgres:16).
"""

import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from connectors.postgres.connector import connector
from connectors.postgres.ephemeral import (
    CONTAINER_PREFIX,
    apply_ddl,
    docker_available,
    ephemeral_postgres,
)
from connectors.sdk.runner import Job, run_job
from snapshot.canonical import canonical_body_bytes
from snapshot.hashing import schema_hash
from snapshot.registry import registered_stats_fields
from snapshot.validate import validate_snapshot
from tests.conftest import provision_introspection_role

PG_IMAGE = os.environ.get("CTXLAYER_PG_TEST_IMAGE", "postgres:16")
DDL_FILE = Path(__file__).parent / "data" / "postgres-demo.sql"

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not docker_available(), reason="Docker daemon unreachable"),
]


def ddl_config(**overrides) -> dict:
    return {
        "system": "demo",
        "mode": "ddl-file",
        "ddl_files": [str(DDL_FILE)],
        "image": PG_IMAGE,
        **overrides,
    }


def live_config(dsn: str) -> dict:
    return {"system": "demo", "mode": "live", "dsn": dsn}


def run_ok(config: dict) -> dict:
    outcome = run_job(connector, Job.local(config))
    assert outcome.status == "succeeded", outcome.error
    return outcome.snapshot.document


def identity(obj: dict) -> tuple[str, str, str]:
    return (obj["kind"], obj["schema"], obj["name"])


def hashes(doc: dict) -> dict:
    return {identity(o): o["schema_hash"] for o in doc["objects"]}


def get(doc: dict, name: str) -> dict:
    return next(o for o in doc["objects"] if o["name"] == name)


def execute(dsn: str, *statements: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


@pytest.fixture(scope="module")
def ddl_doc_pair():
    """Two complete ddl-file runs, each on its own fresh container (C-2)."""
    return run_ok(ddl_config()), run_ok(ddl_config())


@pytest.fixture(scope="module")
def ddl_doc(ddl_doc_pair):
    return ddl_doc_pair[0]


@pytest.fixture(scope="module")
def pristine_dsn():
    """A live server with the same DDL applied, kept up for live-mode runs.

    Handed out as the **introspection role's** DSN, not `postgres`: since
    D-71.2 the connector refuses live introspection over a
    SUPERUSER/BYPASSRLS connection, so this is what live mode now means.
    It also upgrades C-3 below — ddl-file mode introspects as the
    container superuser, live mode as a role with no table privileges at
    all, and the two canonical bodies must still be byte-identical. That
    is the F3 swap's safety argument, executed as conformance.
    """
    with ephemeral_postgres(PG_IMAGE) as (name, dsn):
        apply_ddl(name, [DDL_FILE])
        yield provision_introspection_role(name, dsn, "pristine-introspect-pw")


@pytest.fixture(scope="module")
def live_doc(pristine_dsn):
    return run_ok(live_config(pristine_dsn))


@pytest.fixture(scope="module")
def scratch():
    """A mutable server; every test takes its own before/after pair, so
    accumulated mutations from earlier tests never leak into a comparison.

    Two DSNs, because the two jobs need different rights: `.admin` stages
    the DDL/DML a test wants to observe, `.dsn` is the introspection role
    the connector reads it back through (D-71.2).
    """
    with ephemeral_postgres(PG_IMAGE) as (name, dsn):
        apply_ddl(name, [DDL_FILE])
        yield SimpleNamespace(
            admin=dsn,
            dsn=provision_introspection_role(name, dsn, "scratch-introspect-pw"),
        )


# --- C-2 / C-3: task 1.2 exit criteria ---


def test_c2_ddl_mode_reruns_byte_identical(ddl_doc_pair):
    first, second = ddl_doc_pair
    assert canonical_body_bytes(first) == canonical_body_bytes(second)


def test_c2_live_mode_reruns_byte_identical(pristine_dsn, live_doc):
    again = run_ok(live_config(pristine_dsn))
    assert canonical_body_bytes(again) == canonical_body_bytes(live_doc)


def test_c3_mode_invariance(ddl_doc, live_doc):
    assert ddl_doc["source_mode"] == "ddl-file"
    assert live_doc["source_mode"] == "live"
    assert canonical_body_bytes(ddl_doc) == canonical_body_bytes(live_doc)


# --- C-1 / C-4 / C-8 on real connector output ---


def test_c1_emitted_snapshots_validate(ddl_doc, live_doc):
    for doc in (ddl_doc, live_doc):
        errors, warnings = validate_snapshot(doc, check_hashes=True)
        assert errors == [] and warnings == []


def test_c4_stored_hashes_reproducible(ddl_doc):
    for obj in ddl_doc["objects"]:
        assert schema_hash(obj) == obj["schema_hash"], identity(obj)


def test_c8_stats_contain_only_registered_fields(ddl_doc):
    for obj in ddl_doc["objects"]:
        assert set(obj["stats"]) <= registered_stats_fields(obj["kind"]), identity(obj)


# --- S-2 at the source: C-5 / C-6 staged with real DDL ---


def test_s2_comment_edit_moves_body_never_hashes(scratch):
    before = run_ok(live_config(scratch.dsn))
    execute(
        scratch.admin,
        "COMMENT ON TABLE public.orders IS 'Edited table comment.'",
        "COMMENT ON COLUMN public.orders.status IS 'Edited column comment.'",
    )
    after = run_ok(live_config(scratch.dsn))
    assert canonical_body_bytes(after) != canonical_body_bytes(before)
    assert hashes(after) == hashes(before)  # C-5: no hash moves on comment edits
    assert get(after, "orders")["description"] == "Edited table comment."


def test_c6_structural_change_moves_exactly_one_hash(scratch):
    before = run_ok(live_config(scratch.dsn))
    execute(scratch.admin, "ALTER TABLE public.order_items ADD COLUMN unit_price_cents integer")
    after = run_ok(live_config(scratch.dsn))
    changed = {i for i, h in hashes(before).items() if hashes(after)[i] != h}
    assert changed == {("table", "public", "order_items")}


def test_ordinal_is_dense_rank_after_column_drop(scratch):
    execute(scratch.admin, "ALTER TABLE public.users DROP COLUMN full_name")
    doc = run_ok(live_config(scratch.dsn))
    cols = get(doc, "users")["columns"]
    assert [c["name"] for c in cols] == ["id", "email", "created_at"]
    assert [c["ordinal"] for c in cols] == [1, 2, 3]  # no attnum gap (D-19)


def test_row_estimate_appears_after_analyze_without_hash_motion(scratch):
    before = run_ok(live_config(scratch.dsn))
    assert "row_estimate" not in get(before, "order_items")["stats"]  # reltuples = -1
    execute(
        scratch.admin,
        "INSERT INTO public.users (email) VALUES ('a@x.com'), ('b@x.com'), ('c@x.com')",
        "ANALYZE public.users",
    )
    after = run_ok(live_config(scratch.dsn))
    assert get(after, "users")["stats"]["row_estimate"] == 3
    assert hashes(after) == hashes(before)  # hash-excluded (S-2)


# --- catalog → object-model mapping, as confirmed for task 1.2 ---


def test_estate_identities_and_partition_children_excluded(ddl_doc):
    assert {identity(o) for o in ddl_doc["objects"]} == {
        ("table", "public", "users"),
        ("table", "public", "orders"),
        ("table", "public", "order_items"),
        ("table", "public", "events"),  # partitioned parent: the logical estate
        ("view", "reporting", "v_daily_revenue"),
        ("materialized_view", "public", "mv_user_ltv"),
    }  # events_2026_* children are runtime artifacts, excluded (D-17)


def test_column_mapping_users(ddl_doc):
    cols = {c["name"]: c for c in get(ddl_doc, "users")["columns"]}
    assert cols["id"]["type"] == "uuid"
    assert cols["id"]["default"] == "gen_random_uuid()"
    assert cols["id"]["nullable"] is False
    assert cols["created_at"]["type"] == "timestamp with time zone"
    assert cols["created_at"]["default"] == "now()"
    assert cols["full_name"]["nullable"] is True
    assert [c["ordinal"] for c in get(ddl_doc, "users")["columns"]] == [1, 2, 3, 4]


def test_column_mapping_orders(ddl_doc):
    cols = {c["name"]: c for c in get(ddl_doc, "orders")["columns"]}
    assert cols["id"]["type"] == "bigint"
    assert cols["id"]["default"] is None  # identity marker: no v1 slot (SS-7)
    assert cols["total_dollars"]["type"] == "numeric(12,2)"
    assert cols["total_dollars"]["default"] is None  # generated: no v1 slot (SS-7)
    assert cols["status"]["type"] == "public.order_status"  # enum type, qualified
    assert cols["status"]["default"] == "'pending'::public.order_status"


def test_descriptions_verbatim(ddl_doc):
    assert (
        get(ddl_doc, "users")["description"]
        == "Registered accounts. Rows are soft-deleted via deleted_at."
    )
    cols = {c["name"]: c for c in get(ddl_doc, "users")["columns"]}
    assert (
        cols["email"]["description"]
        == "Lowercased at the application layer; citext migration pending."
    )
    assert get(ddl_doc, "v_daily_revenue")["description"] == "Paid revenue per calendar day."


def test_keys_mapping(ddl_doc):
    users, orders = get(ddl_doc, "users"), get(ddl_doc, "orders")
    items = get(ddl_doc, "order_items")
    assert users["keys"]["primary"] == ["id"]
    assert users["keys"]["unique"] == [["email"]]
    assert orders["keys"]["foreign"] == [
        {"columns": ["user_id"], "ref": "public.users", "ref_columns": ["id"]}
    ]
    assert items["keys"]["unique"] == [["order_id", "product_sku"]]
    assert "primary" not in items["keys"]  # empty key arrays omitted (D-4)
    assert get(ddl_doc, "v_daily_revenue")["keys"] == {}


def test_indexes_mapping(ddl_doc):
    orders = get(ddl_doc, "orders")["stats"]["indexes"]
    assert orders == sorted(orders) and len(orders) == 2
    assert any("UNIQUE" in d and "WHERE" in d for d in orders)  # unique partial index
    assert all("public.orders" in d for d in orders)  # qualified deparse
    # a bare unique index is a physical artifact, never keys.unique (§4.5 caveat)
    assert "unique" not in get(ddl_doc, "orders")["keys"]
    # users has only constraint-backing indexes → omitted entirely
    assert "indexes" not in get(ddl_doc, "users")["stats"]
    assert get(ddl_doc, "mv_user_ltv")["stats"]["indexes"] == [
        "CREATE UNIQUE INDEX mv_user_ltv_user_idx ON public.mv_user_ltv USING btree (user_id)"
    ]


# --- SS-5: CHECK constraints at the boundary (§4.5, ruling D-96.3d) ---


def test_ss5_checks_captured_verbatim_and_sorted(ddl_doc):
    checks = get(ddl_doc, "orders")["stats"]["checks"]
    # Verbatim pg_get_constraintdef(oid, true) output — the engine's own
    # rendering, never parsed into a value set on this side (S-8). The
    # `true` is pretty-print, matching how view definitions are already
    # taken (`pg_get_viewdef(oid, true)`), so both read the same way.
    assert checks == ["CHECK (total_cents >= 0)"]
    assert checks == sorted(checks)  # §4.5 registered form


def test_ss5_checks_omitted_where_the_kind_has_none(ddl_doc):
    # Absent, not empty: `{}` and `{"checks": []}` hash differently, so
    # there is exactly one form for "no CHECKs" (D-4).
    assert "checks" not in get(ddl_doc, "users")["stats"]
    # Registered on `table` only — a view/matview must never carry it.
    assert "checks" not in get(ddl_doc, "v_daily_revenue")["stats"]
    assert "checks" not in get(ddl_doc, "mv_user_ltv")["stats"]


def test_ss5_not_null_is_not_a_check(ddl_doc):
    # NOT NULL is already `columns[].nullable`; on PG17+ it also appears
    # in pg_constraint as contype 'n'. The contype='c' filter excludes it
    # by construction, so the fact is carried once, in one place.
    orders = get(ddl_doc, "orders")
    assert not any("NOT NULL" in c for c in orders["stats"]["checks"])
    assert any(c["name"] == "total_cents" and not c["nullable"] for c in orders["columns"])


def test_ss5_check_is_hash_included_so_a_widened_constraint_contaminates(scratch):
    """The polarity argument, executed.

    This is the D-86.3b case in miniature: `ai_runs.status` was documented
    from a CHECK vocabulary. If widening that CHECK moved no hash, the doc
    explaining it would stay `verified` while the source no longer backed
    it. Hash-included is what makes the drift reachable by the
    contamination scan.
    """
    before = run_ok(live_config(scratch.dsn))
    execute(
        scratch.admin,
        "ALTER TABLE public.orders DROP CONSTRAINT orders_total_cents_check",
        "ALTER TABLE public.orders ADD CONSTRAINT orders_total_cents_check "
        "CHECK (total_cents >= -100)",
    )
    after = run_ok(live_config(scratch.dsn))

    assert get(after, "orders")["stats"]["checks"] == ["CHECK (total_cents >= '-100'::integer)"]
    # Exactly one hash moves, and it is the table whose constraint changed.
    changed = {i for i, h in hashes(before).items() if hashes(after)[i] != h}
    assert changed == {("table", "public", "orders")}


def test_ss5_multiple_checks_sort_lexicographically(scratch):
    # pg_constraint order is not stable across dump/restore, so the sort
    # is what C-2 byte-identity rests on when a table has several CHECKs.
    execute(
        scratch.admin,
        "ALTER TABLE public.users ADD CONSTRAINT aa_users_email_len CHECK (length(email) > 3)",
        "ALTER TABLE public.users ADD CONSTRAINT zz_users_created_past "
        "CHECK (created_at < 'infinity'::timestamptz)",
    )
    doc = run_ok(live_config(scratch.dsn))
    checks = get(doc, "users")["stats"]["checks"]
    assert len(checks) == 2
    assert checks == sorted(checks)
    # Sorted by rendered definition, not by constraint name: the `aa_`/`zz_`
    # names are deliberately anti-correlated with the expression text, so a
    # sort-by-name regression puts them in the wrong order here.
    assert checks[0].startswith("CHECK (created_at")
    assert checks[1].startswith("CHECK (length(email)")


def test_view_definition_verbatim_and_qualified(ddl_doc):
    definition = get(ddl_doc, "v_daily_revenue")["stats"]["definition"]
    assert "public.orders o" in definition  # search_path = '' → qualified (D-19)
    assert definition.strip().startswith("SELECT")
    assert "definition" in get(ddl_doc, "mv_user_ltv")["stats"]


def test_partitioned_parent_is_a_plain_table_fact(ddl_doc):
    events = get(ddl_doc, "events")
    assert events["kind"] == "table"
    assert "row_estimate" not in events["stats"]


def test_envelope_and_source_properties(ddl_doc):
    assert ddl_doc["system_class"] == "sql"
    assert re.fullmatch(r"\d+\.\d+", ddl_doc["source_properties"]["server_version"])
    assert ddl_doc["connector"]["name"] == "postgres"


# --- failure path that needs Docker: DDL rejected by real Postgres ---


def _our_containers() -> set[str]:
    proc = subprocess.run(
        ["docker", "ps", "--all", "--filter", f"name={CONTAINER_PREFIX}", "--quiet"],
        capture_output=True,
        text=True,
    )
    return set(proc.stdout.split())


def test_bad_ddl_fails_config_error_nothing_emitted_no_leftovers(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("CREATE TABLEE nope (id int);\n", encoding="utf-8")
    running_before = _our_containers()
    outcome = run_job(connector, Job.local(ddl_config(ddl_files=[str(bad)])))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.error.retryable is False
    assert outcome.snapshot is None  # S-6: nothing partial
    assert _our_containers() == running_before  # ephemeral container torn down
