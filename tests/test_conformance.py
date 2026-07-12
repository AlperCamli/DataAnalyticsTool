"""Conformance suite (spec §9, C-1..C-8), run on the checked-in fixtures.

C-2, C-3, and C-7 need a live source and/or the job transport; they are
skipped here with the reason recorded and land with tasks 1.2–1.4 (the SDK
ships this suite as the reusable harness those tasks run green).
"""

import copy

import pytest

from snapshot.canonical import canonical_body_bytes
from snapshot.hashing import schema_hash
from snapshot.registry import registered_stats_fields
from snapshot.validate import validate_snapshot
from tests.conftest import FIXTURE_FILES, find_object, load_fixture


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_c1_fixtures_validate_against_schema(name):
    errors, _ = validate_snapshot(load_fixture(name))
    assert errors == []


@pytest.mark.skip(
    reason="C-2 (S-3) requires two live introspection runs against an "
    "unchanged source; connector-level. Postgres: green in "
    "test_postgres_connector.py (task 1.2); GA4/GSC land with 1.3/1.4. "
    "The canonicalization half is covered by the property tests."
)
def test_c2_reruns_byte_identical():
    pass


@pytest.mark.skip(
    reason="C-3 (S-4) requires introspecting the same source state through "
    "every supported source_mode (ddl-file vs live); task 1.2 exit "
    "criterion — green for postgres in test_postgres_connector.py. "
    "This placeholder stays for future multi-mode connectors."
)
def test_c3_mode_invariance():
    pass


def test_fixture_pair_canonical_body_identity():
    """supabase-live.json is hand-derived from supabase-ddl.json (D-7):
    this proves the canonical-body comparison machinery, not connector
    mode-invariance — that is the skipped C-3 above."""
    ddl = load_fixture("supabase-ddl.json")
    live = load_fixture("supabase-live.json")
    assert ddl["source_mode"] != live["source_mode"]
    assert ddl["captured_at"] != live["captured_at"]
    assert canonical_body_bytes(ddl) == canonical_body_bytes(live)


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_c4_stored_hashes_reproducible(name):
    for obj in load_fixture(name)["objects"]:
        assert schema_hash(obj) == obj["schema_hash"], (
            f"{obj['schema']}.{obj['name']} ({obj['kind']})"
        )


def test_c5_description_only_change_moves_body_not_hashes():
    snap = load_fixture("supabase-ddl.json")
    edited = copy.deepcopy(snap)
    orders = find_object(edited, "orders")
    orders["description"] = "Edited table comment."
    orders["columns"][2]["description"] = "Edited column comment."
    assert canonical_body_bytes(edited) != canonical_body_bytes(snap)
    for before, after in zip(snap["objects"], edited["objects"]):
        assert schema_hash(after) == schema_hash(before)


def test_c6_structural_change_moves_exactly_affected_hashes():
    snap = load_fixture("supabase-ddl.json")
    edited = copy.deepcopy(snap)
    orders = find_object(edited, "orders")
    orders["columns"].append({
        "name": "coupon_code", "type": "text", "nullable": True,
        "default": None, "ordinal": 7, "description": None,
    })
    changed = [
        o["name"]
        for o, e in zip(snap["objects"], edited["objects"])
        if schema_hash(e) != schema_hash(o)
    ]
    assert changed == ["orders"]


@pytest.mark.skip(
    reason="C-7 (S-6) requires the job transport and a connector that can "
    "fail mid-introspection (no snapshot emitted, job dead-letters). "
    "Engine half: test_sdk_runner (demo injection); postgres failure "
    "paths: test_postgres_config.py + the bad-DDL container test. The "
    "dead-letter half lands with the job-protocol transport."
)
def test_c7_partial_introspection_fails_job():
    pass


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_c8_stats_contain_only_registered_fields(name):
    for obj in load_fixture(name)["objects"]:
        allowed = registered_stats_fields(obj["kind"])
        assert set(obj["stats"]) <= allowed, (
            f"{obj['schema']}.{obj['name']}: undeclared stats "
            f"{set(obj['stats']) - allowed} (S-7)"
        )
