"""Renderer contract: KB-8 idempotency, D-33 Rule B, mode pair, S-5 skip.

The mode-pair test asserts both halves of the Ruling-1 interaction: the
`source_mode` byte-range on same-date renders, and the restamp when a
mode switch arrives with a later capture date.
"""

import copy
import json
import logging

import pytest

from generator.render import GeneratorError, main, render_tree
from tests.conftest import (
    changed_paths,
    human_object_doc,
    load_fixture,
    tree_bytes,
)

THREE = ("supabase-ddl.json", "ga4.json", "gsc.json")


def render(tmp_path, *names_or_snaps):
    snaps = [
        load_fixture(x) if isinstance(x, str) else x for x in names_or_snaps
    ]
    return render_tree(snaps, tmp_path)


def machine_paths(tree: dict[str, bytes]) -> set[str]:
    return {
        rel
        for rel in tree
        if rel.startswith("systems/")
        and (rel.endswith(".schema.md") or rel.endswith("index.md"))
    }


def test_kb8_regeneration_is_byte_level_no_op(tmp_path):
    first = render(tmp_path, *THREE)
    before = tree_bytes(tmp_path)
    second = render(tmp_path, *THREE)
    assert tree_bytes(tmp_path) == before
    assert second.written == [] and second.deleted == []
    assert sorted(second.unchanged) == sorted(
        first.written
    )  # every machine file re-planned, none rewritten
    assert second.bootstrapped == []


def test_fresh_render_is_pure_function_of_snapshots(tmp_path):
    a_dir, b_dir = tmp_path / "a", tmp_path / "b"
    render(a_dir, *THREE)

    shuffled = []
    for name in reversed(THREE):
        snap = load_fixture(name)
        snap["objects"] = list(reversed(snap["objects"]))  # storage order is noise
        shuffled.append(snap)
    render_tree(shuffled, b_dir)

    assert tree_bytes(a_dir) == tree_bytes(b_dir)


def test_mode_pair_differs_only_in_source_mode_byte_range(tmp_path):
    """S-4/D-1 flow-through: ddl-file and live snapshots of the same source
    state (same capture date) render trees identical except the
    `source_mode:` front-matter line of machine files."""
    ddl_dir, live_dir = tmp_path / "ddl", tmp_path / "live"
    render(ddl_dir, "supabase-ddl.json")
    render(live_dir, "supabase-live.json")

    ddl, live = tree_bytes(ddl_dir), tree_bytes(live_dir)
    assert set(ddl) == set(live)
    for rel in ddl:
        if rel in machine_paths(ddl):
            assert ddl[rel] != live[rel], rel
            patched = ddl[rel].replace(
                b"source_mode: ddl-file", b"source_mode: live"
            )
            assert patched == live[rel], rel
        else:  # bootstrapped root files carry no provenance
            assert ddl[rel] == live[rel], rel


def test_mode_switch_restamps_generated_at(tmp_path):
    """Ruling 1: the ddl→live switch is a content change, so every machine
    file of the system restamps to the live snapshot's capture date."""
    render(tmp_path, "supabase-ddl.json")
    live = load_fixture("supabase-live.json")
    live["captured_at"] = "2026-07-12T02:00:00Z"
    result = render_tree([live], tmp_path)

    tree = tree_bytes(tmp_path)
    machine = machine_paths(tree)
    assert sorted(result.written) == sorted(machine)  # all rewritten
    for rel in machine:
        assert b"source_mode: live" in tree[rel], rel
        assert b"generated_at: 2026-07-12" in tree[rel], rel


def test_unknown_kind_skipped_with_logged_warning(tmp_path, caplog):
    snap = load_fixture("supabase-ddl.json")
    snap["objects"].append(
        {
            "kind": "widget",
            "schema": "public",
            "name": "gizmo",
            "description": None,
            "schema_hash": "sha256:" + "0" * 64,
            "columns": [],
            "keys": {},
            "stats": {},
        }
    )
    with caplog.at_level(logging.WARNING, logger="generator"):
        render_tree([snap], tmp_path)

    assert any("widget" in r.message for r in caplog.records)
    tree = tree_bytes(tmp_path)
    assert not any("gizmo" in rel for rel in tree)
    assert "systems/supabase/public/orders.schema.md" in tree  # rest rendered
    # the skipped kind is invisible in the index too (S-5)
    assert b"gizmo" not in tree["systems/supabase/public/index.md"]


def test_hot_stub_flip_touches_only_indexes(tmp_path):
    render(tmp_path, *THREE)
    before = tree_bytes(tmp_path)

    snap = load_fixture("supabase-ddl.json")
    orders_hash = next(
        o["schema_hash"] for o in snap["objects"] if o["name"] == "orders"
    )
    human = tmp_path / "systems/supabase/public/orders.md"
    human.write_text(
        human_object_doc("supabase.public.orders", orders_hash), encoding="utf-8"
    )

    render(tmp_path, *THREE)
    after = tree_bytes(tmp_path)
    assert changed_paths(before, after) == {
        "systems/supabase/public/orders.md",  # the planted human doc itself
        "systems/supabase/public/index.md",
        "systems/supabase/index.md",
    }
    idx = after["systems/supabase/public/index.md"].decode()
    assert "[orders.md](orders.md)" in idx and "| draft |" in idx
    assert b"| 1 |" in after["systems/supabase/index.md"]  # human-docs count


def test_bootstrap_writes_once_then_hands_off(tmp_path):
    render(tmp_path, *THREE)
    (tmp_path / "index.md").write_text("# Mine now\n", encoding="utf-8")
    (tmp_path / "conventions.md").write_text("# Edited\n", encoding="utf-8")
    result = render(tmp_path, *THREE)
    assert result.bootstrapped == []
    assert (tmp_path / "index.md").read_text() == "# Mine now\n"
    assert (tmp_path / "conventions.md").read_text() == "# Edited\n"


def test_duplicate_system_rejected(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    with pytest.raises(GeneratorError, match="duplicate system"):
        render_tree([snap, copy.deepcopy(snap)], tmp_path)


def test_invalid_snapshot_rejected(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    del snap["system_class"]
    with pytest.raises(GeneratorError, match="invalid snapshot"):
        render_tree([snap], tmp_path)
    assert not any(tmp_path.rglob("*.md"))  # nothing written


def test_cli_exit_codes(tmp_path):
    fixture_dir = tmp_path / "in"
    fixture_dir.mkdir()
    good = fixture_dir / "snap.json"
    good.write_text(json.dumps(load_fixture("gsc.json")), encoding="utf-8")
    assert main([str(good), "--out", str(tmp_path / "kb")]) == 0

    bad = fixture_dir / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert main([str(bad), "--out", str(tmp_path / "kb")]) == 1
