"""Diff engine tests (spec §7) including the task exit criteria:
self-diff empty; dropped column → breaking; added nullable column →
additive; comment-only edit → metadata-only with unchanged schema_hash."""

import copy
import logging

import pytest

from snapshot.diff import (
    ADDITIVE,
    ADDITIVE_WITH_NOTE,
    BREAKING,
    DiffError,
    diff_snapshots,
)
from tests.conftest import FIXTURE_FILES, find_object, load_fixture, mutate


def _only_structural(diff):
    assert len(diff.changed_structural) == 1
    assert not (diff.added or diff.removed or diff.changed_metadata_only)
    return diff.changed_structural[0]


def _sub(obj_diff, change):
    matches = [s for s in obj_diff.sub_diffs if s.change == change]
    assert matches, f"no {change} sub-diff in {[s.change for s in obj_diff.sub_diffs]}"
    return matches


# ------------------------------------------------------------ exit criteria


@pytest.mark.parametrize("name", FIXTURE_FILES)
def test_self_diff_is_empty(name):
    snap = load_fixture(name)
    diff = diff_snapshots(snap, copy.deepcopy(snap), verify_hashes=True)
    assert diff.is_empty()
    assert len(diff.unchanged) == len(snap["objects"])


def test_dropped_column_is_breaking(supabase):
    changed = mutate(supabase, "orders", lambda o: o["columns"].pop(4))  # notes
    obj = _only_structural(diff_snapshots(supabase, changed))
    (sub,) = _sub(obj, "column_removed")
    assert sub.severity == BREAKING
    assert sub.detail["column"] == "notes"
    assert obj.severity == BREAKING
    assert not obj.rename_candidates


def test_added_nullable_column_is_additive(supabase):
    changed = mutate(supabase, "orders", lambda o: o["columns"].append({
        "name": "coupon_code", "type": "text", "nullable": True,
        "default": None, "ordinal": 7, "description": None,
    }))
    obj = _only_structural(diff_snapshots(supabase, changed))
    (sub,) = _sub(obj, "column_added")
    assert sub.severity == ADDITIVE
    assert obj.severity == ADDITIVE
    assert [s.change for s in obj.sub_diffs] == ["column_added"]


def test_comment_only_edit_is_metadata_only_with_unchanged_hash(supabase):
    def edit(o):
        o["description"] = "Edited table comment."
        o["columns"][2]["description"] = "Edited column comment."

    changed = mutate(supabase, "orders", edit)  # rehash: hash must not move
    before = find_object(supabase, "orders")["schema_hash"]
    after = find_object(changed, "orders")["schema_hash"]
    assert after == before, "S-2: comment edits must not move schema_hash"

    diff = diff_snapshots(supabase, changed, verify_hashes=True)
    assert not (diff.added or diff.removed or diff.changed_structural)
    (obj,) = diff.changed_metadata_only
    assert obj.identity == ("table", "public", "orders")
    assert "description" in obj.metadata_changes
    assert "columns.status.description" in obj.metadata_changes


# --------------------------------------------------------- §7 severity table


def test_type_change_is_breaking(supabase):
    changed = mutate(
        supabase, "orders",
        lambda o: o["columns"][3].update(type="bigint"),  # total_cents
    )
    obj = _only_structural(diff_snapshots(supabase, changed))
    (sub,) = _sub(obj, "column_type_changed")
    assert sub.severity == BREAKING
    assert sub.detail == {"column": "total_cents", "from": "integer", "to": "bigint"}


def test_nullable_tightened_breaking_loosened_additive_with_note(supabase):
    tightened = mutate(
        supabase, "orders", lambda o: o["columns"][4].update(nullable=False)
    )
    obj = _only_structural(diff_snapshots(supabase, tightened))
    assert _sub(obj, "column_nullable_tightened")[0].severity == BREAKING

    loosened = mutate(
        supabase, "orders", lambda o: o["columns"][1].update(nullable=True)
    )
    obj = _only_structural(diff_snapshots(supabase, loosened))
    assert _sub(obj, "column_nullable_loosened")[0].severity == ADDITIVE_WITH_NOTE
    assert obj.severity == ADDITIVE_WITH_NOTE


def test_default_change_is_additive_with_note(supabase):
    changed = mutate(
        supabase, "orders",
        lambda o: o["columns"][2].update(default="'created'::text"),
    )
    obj = _only_structural(diff_snapshots(supabase, changed))
    assert _sub(obj, "column_default_changed")[0].severity == ADDITIVE_WITH_NOTE


def test_ordinal_change_is_breaking_per_d2(supabase):
    def swap(o):
        o["columns"][3]["ordinal"], o["columns"][4]["ordinal"] = (
            o["columns"][4]["ordinal"], o["columns"][3]["ordinal"],
        )

    changed = mutate(supabase, "orders", swap)
    obj = _only_structural(diff_snapshots(supabase, changed))
    assert all(s.severity == BREAKING for s in _sub(obj, "column_ordinal_changed"))


def test_key_added_removed_altered(supabase):
    added = mutate(
        supabase, "orders",
        lambda o: o["keys"].update(unique=[["user_id", "created_at"]]),
    )
    obj = _only_structural(diff_snapshots(supabase, added))
    assert _sub(obj, "key_added")[0].severity == ADDITIVE

    removed = mutate(supabase, "orders", lambda o: o["keys"].pop("foreign"))
    obj = _only_structural(diff_snapshots(supabase, removed))
    (sub,) = _sub(obj, "key_removed")
    assert sub.severity == BREAKING and sub.detail["key"] == "foreign"

    altered = mutate(
        supabase, "orders",
        lambda o: o["keys"]["foreign"][0].update(ref_columns=["email"]),
    )
    obj = _only_structural(diff_snapshots(supabase, altered))
    (sub,) = _sub(obj, "key_altered")
    assert sub.severity == BREAKING

    pk_altered = mutate(
        supabase, "orders", lambda o: o["keys"].update(primary=["id", "user_id"])
    )
    obj = _only_structural(diff_snapshots(supabase, pk_altered))
    (sub,) = _sub(obj, "key_altered")
    assert sub.severity == BREAKING and sub.detail["key"] == "primary"


def test_view_definition_change_is_breaking_and_downgradable(supabase):
    changed = mutate(
        supabase, "v_daily_revenue",
        lambda o: o["stats"].update(
            definition=o["stats"]["definition"].replace("'paid'", "'settled'")
        ),
    )
    obj = _only_structural(diff_snapshots(supabase, changed))
    (sub,) = _sub(obj, "definition_changed")
    assert sub.severity == BREAKING
    assert sub.downgradable, "D-3: sync engine downgrades via lineage (§7 fn 3)"


def test_api_data_type_change_is_breaking(ga4):
    changed = mutate(
        ga4, "activeUsers", lambda o: o["stats"].update(data_type="TYPE_FLOAT")
    )
    obj = _only_structural(diff_snapshots(ga4, changed))
    (sub,) = _sub(obj, "stat_changed")
    assert sub.severity == BREAKING and sub.detail["stat"] == "data_type"


def test_key_event_toggle_is_breaking_per_d2(ga4):
    changed = mutate(
        ga4, "plan_upgraded", lambda o: o["stats"].update(is_key_event=True)
    )
    obj = _only_structural(diff_snapshots(ga4, changed))
    (sub,) = _sub(obj, "stat_changed")
    assert sub.severity == BREAKING and sub.detail["stat"] == "is_key_event"
    assert obj.identity == ("api_event", "custom", "plan_upgraded"), (
        "D-5: key-event promotion keeps identity stable"
    )


def test_row_estimate_only_change_is_metadata_only(supabase):
    """SS-4 default: row_estimate is hash-excluded, so drift never scans."""
    changed = mutate(
        supabase, "orders", lambda o: o["stats"].update(row_estimate=999999)
    )
    diff = diff_snapshots(supabase, changed, verify_hashes=True)
    (obj,) = diff.changed_metadata_only
    assert obj.metadata_changes == ["stats.row_estimate"]


# ------------------------------------------------- identity, renames, guards


def test_added_and_removed_objects(supabase):
    changed = copy.deepcopy(supabase)
    removed_obj = find_object(changed, "products")
    changed["objects"].remove(removed_obj)
    diff = diff_snapshots(supabase, changed)
    (obj,) = diff.removed
    assert obj.identity == ("table", "public", "products")
    assert obj.severity == BREAKING

    diff = diff_snapshots(changed, supabase)
    (obj,) = diff.added
    assert obj.identity == ("table", "public", "products")
    assert obj.severity == ADDITIVE


def test_rename_candidate_flagged_with_both_interpretations(supabase):
    changed = mutate(
        supabase, "orders", lambda o: o["columns"][3].update(name="amount_cents")
    )
    obj = _only_structural(diff_snapshots(supabase, changed))
    assert _sub(obj, "column_removed")[0].severity == BREAKING
    assert _sub(obj, "column_added")[0].severity == ADDITIVE
    (candidate,) = obj.rename_candidates
    assert (candidate.from_column, candidate.to_column) == ("total_cents", "amount_cents")
    assert candidate.type == "integer" and candidate.ordinal == 4
    assert len(candidate.to_dict()["interpretations"]) == 2


def test_drift_pair_stages_every_classification():
    diff = diff_snapshots(
        load_fixture("drift-pair/before.json"),
        load_fixture("drift-pair/after.json"),
        verify_hashes=True,
    )
    assert [d.identity[2] for d in diff.added] == ["coupons"]
    assert [d.identity[2] for d in diff.removed] == ["legacy_sessions"]
    assert sorted(d.identity[2] for d in diff.changed_structural) == [
        "orders", "v_daily_revenue",
    ]
    assert [d.identity[2] for d in diff.changed_metadata_only] == ["products"]
    assert [name for (_, _, name) in diff.unchanged] == ["users"]

    orders = next(d for d in diff.changed_structural if d.identity[2] == "orders")
    (candidate,) = orders.rename_candidates
    assert (candidate.from_column, candidate.to_column) == ("total_cents", "amount_cents")
    changes = {s.change for s in orders.sub_diffs}
    assert {"column_added", "column_removed", "column_default_changed"} <= changes


def test_different_systems_refused(supabase, ga4):
    with pytest.raises(DiffError, match="different systems"):
        diff_snapshots(supabase, ga4)


def test_duplicate_identity_refused(supabase):
    changed = copy.deepcopy(supabase)
    changed["objects"].append(copy.deepcopy(find_object(changed, "orders")))
    with pytest.raises(DiffError, match="duplicate object identity"):
        diff_snapshots(supabase, changed)


def test_unknown_kind_skipped_with_warning(supabase, caplog):
    changed = copy.deepcopy(supabase)
    changed["objects"].append({
        "kind": "function", "schema": "public", "name": "fn_refresh_ltv",
        "description": None, "schema_hash": "sha256:" + "0" * 64,
        "columns": [], "keys": {}, "stats": {},
    })
    with caplog.at_level(logging.WARNING, logger="snapshot.diff"):
        diff = diff_snapshots(supabase, changed)
    assert diff.is_empty(), "S-5: unknown kinds never classify, never error"
    assert diff.skipped_unknown_kinds == [("function", "public", "fn_refresh_ltv")]
    assert any("unknown kind 'function'" in r.message for r in caplog.records)


def test_verify_hashes_catches_tampered_hash(supabase):
    tampered = mutate(
        supabase, "orders",
        lambda o: o.update(schema_hash="sha256:" + "f" * 64),
        rehash=False,
    )
    with pytest.raises(DiffError, match="C-4"):
        diff_snapshots(supabase, tampered, verify_hashes=True)
