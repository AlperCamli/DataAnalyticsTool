"""machine-kb condition builder (benchmark.conditions, R1)."""

import pytest

from benchmark.conditions import (
    build_machine_kb,
    is_machine_file,
    machine_kb_condition,
    no_kb_condition,
)
from tests.conftest import tree_bytes


def test_build_produces_only_machine_files(tmp_path):
    build = build_machine_kb(tmp_path / "mkb")
    assert build.files  # non-empty
    assert all(is_machine_file(rel) for rel in build.files)
    # The machine docs the estate defines are present.
    assert "systems/supabase/public/users.schema.md" in build.files
    assert "systems/ga4/metrics.schema.md" in build.files
    assert "index.md" in build.files and "conventions.md" in build.files


def test_build_excludes_human_owned_files(tmp_path):
    build = build_machine_kb(tmp_path / "mkb")
    human_owned = {
        "entities/user.md", "entities/page.md", "entities/conversion.md",
        "systems/supabase/public/users.md", "systems/supabase/public/subscriptions.md",
        "systems/gsc/_notes.md", "systems/ga4/metrics.md", "systems/gsc/dimensions.md",
        "lineage/graph.json",
    }
    assert human_owned.isdisjoint(set(build.files))


def test_empty_enrichment_renders_dash(tmp_path):
    build = build_machine_kb(tmp_path / "mkb")
    users = (build.out_dir / "systems/supabase/public/users.schema.md").read_text("utf-8")
    # Purpose + Description slots render the absent-fact marker, not prose.
    assert "| Purpose |" in users
    assert "— | — |" in users


def test_build_is_deterministic_byte_identical(tmp_path):
    a = build_machine_kb(tmp_path / "a")
    b = build_machine_kb(tmp_path / "b")
    assert a.manifest == b.manifest
    assert a.ref == b.ref
    assert tree_bytes(a.out_dir) == tree_bytes(b.out_dir)  # C-2-style identity


def test_ref_is_content_addressed(tmp_path):
    build = build_machine_kb(tmp_path / "mkb")
    assert build.ref.startswith("sha256:")
    # Tampering a file changes the ref recomputation.
    (build.out_dir / "index.md").write_text("tampered\n", encoding="utf-8")
    rebuilt = build_machine_kb(tmp_path / "mkb2")
    from benchmark.conditions import _manifest_ref, _sha256_file
    tampered_manifest = {
        rel: _sha256_file(build.out_dir / rel) for rel in build.files
    }
    assert _manifest_ref(tampered_manifest) != rebuilt.ref


def test_leak_detection_trips_on_human_file(tmp_path):
    out = tmp_path / "mkb"
    build_machine_kb(out)
    # Simulate a human doc surviving in the tree; a re-render without clean
    # must refuse it.
    (out / "systems/supabase/public/users.md").write_text("human\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="leaked human-owned"):
        build_machine_kb(out, clean=False)


def test_condition_constructors(tmp_path):
    assert no_kb_condition().context_root is None
    assert no_kb_condition().ref == "live-discovery"
    cond = machine_kb_condition(tmp_path / "mkb")
    assert cond.name == "machine-kb" and cond.context_root == tmp_path / "mkb"
    assert cond.ref.startswith("sha256:")


def test_is_machine_file_predicate():
    assert is_machine_file("systems/supabase/public/users.schema.md")
    assert is_machine_file("systems/ga4/index.md")
    assert is_machine_file("conventions.md")
    assert not is_machine_file("systems/supabase/public/users.md")  # human object doc
    assert not is_machine_file("entities/user.md")
    assert not is_machine_file("lineage/graph.json")
