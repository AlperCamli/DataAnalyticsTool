"""Validation library: front-matter schemas, layout conformance, and the
snapshot cross-checks (missing/orphan machine docs, provenance drift).
End-to-end smoke: the three real snapshots render and validate green."""

import pytest

from generator.render import render_tree
from generator.validate import main, validate_tree
from tests.conftest import FIXTURES_DIR, human_object_doc, load_fixture

THREE = ("supabase-ddl.json", "ga4.json", "gsc.json")


@pytest.fixture
def kb(tmp_path):
    snaps = [load_fixture(n) for n in THREE]
    render_tree(snaps, tmp_path)
    return tmp_path, snaps


def findings_by_check(findings):
    return {f.check for f in findings}


def test_smoke_rendered_tree_is_green(kb):
    kb_dir, snaps = kb
    assert validate_tree(kb_dir) == []
    assert validate_tree(kb_dir, snaps) == []


def test_root_bootstrap_files_are_exempt(kb):
    kb_dir, _ = kb
    # no front-matter on either — §4.6 exemption, not a KB-1 finding
    assert not (kb_dir / "index.md").read_text().startswith("---")
    assert validate_tree(kb_dir) == []


def test_valid_human_docs_pass_and_notes_are_exempt(kb):
    kb_dir, snaps = kb
    orders_hash = next(
        o["schema_hash"] for o in snaps[0]["objects"] if o["name"] == "orders"
    )
    (kb_dir / "systems/supabase/public/orders.md").write_text(
        human_object_doc("supabase.public.orders", orders_hash), encoding="utf-8"
    )
    (kb_dir / "systems/supabase/_notes.md").write_text("free narrative\n")

    # the new human docs flip hot/stub cells: KB-8 (D-49) demands the
    # implied index re-renders land in the same PR
    findings = validate_tree(kb_dir, snaps)
    assert findings and {f.check for f in findings} == {"KB-8"}

    render_tree(snaps, kb_dir)
    assert validate_tree(kb_dir, snaps) == []


def test_faults_dir_is_flagged(kb):
    kb_dir, _ = kb
    (kb_dir / "faults").mkdir()
    findings = validate_tree(kb_dir)
    assert [f for f in findings if f.path == "faults" and f.check == "layout"]


def test_unparseable_front_matter_is_kb1(kb):
    kb_dir, _ = kb
    target = kb_dir / "systems/supabase/public/orders.schema.md"
    target.write_text("# no front matter\n", encoding="utf-8")
    findings = validate_tree(kb_dir)
    assert any(
        f.check == "KB-1" and "orders.schema.md" in f.path for f in findings
    )


def test_unregistered_doc_class_is_kb1(kb):
    kb_dir, _ = kb
    (kb_dir / "systems/supabase/public/orders.md").write_text(
        "---\ndoc_class: mystery\n---\n\nbody\n", encoding="utf-8"
    )
    findings = validate_tree(kb_dir)
    assert any("mystery" in f.message and f.check == "KB-1" for f in findings)


def test_unknown_front_matter_key_rejected(kb):
    kb_dir, _ = kb
    target = kb_dir / "systems/gsc/dimensions.schema.md"
    text = target.read_text(encoding="utf-8")
    target.write_text(
        text.replace("status: machine", "status: machine\nextra_key: 1"),
        encoding="utf-8",
    )
    findings = validate_tree(kb_dir)
    assert any("extra_key" in f.message for f in findings)  # closed contract (§4)


def test_machine_class_on_human_path_is_layout_violation(kb):
    kb_dir, _ = kb
    src = (kb_dir / "systems/supabase/public/orders.schema.md").read_text()
    (kb_dir / "systems/supabase/public/orders.md").write_text(src, encoding="utf-8")
    findings = validate_tree(kb_dir)
    assert any(f.check == "layout" and "K-1" in f.message for f in findings)


def test_object_path_mismatch_is_layout_violation(kb):
    kb_dir, _ = kb
    src = (kb_dir / "systems/supabase/public/orders.schema.md").read_text()
    (kb_dir / "systems/supabase/public/renamed.schema.md").write_text(
        src, encoding="utf-8"
    )
    findings = validate_tree(kb_dir)
    assert any(
        f.path.endswith("renamed.schema.md") and "does not map" in f.message
        for f in findings
    )


def test_missing_machine_doc_flagged_with_snapshots(kb):
    kb_dir, snaps = kb
    (kb_dir / "systems/supabase/public/users.schema.md").unlink()
    findings = validate_tree(kb_dir, snaps)
    assert any(
        f.check == "provenance" and f.path.endswith("users.schema.md") for f in findings
    )
    # without snapshots there is no provenance check — but the index's
    # dangling link to the deleted doc still surfaces through KB-5
    without = validate_tree(kb_dir)
    assert {f.check for f in without} == {"KB-5"}


def test_orphan_machine_doc_flagged_with_snapshots(kb):
    kb_dir, snaps = kb
    src = (kb_dir / "systems/supabase/public/orders.schema.md").read_text()
    ghost = src.replace("supabase.public.orders", "supabase.public.ghost").replace(
        "orders.schema.md", "ghost.schema.md"
    )
    (kb_dir / "systems/supabase/public/ghost.schema.md").write_text(
        ghost, encoding="utf-8"
    )
    findings = validate_tree(kb_dir, snaps)
    assert any("orphan machine doc" in f.message for f in findings)


def test_hash_drift_flagged_with_snapshots(kb):
    kb_dir, snaps = kb
    target = kb_dir / "systems/supabase/public/orders.schema.md"
    text = target.read_text(encoding="utf-8")
    stale = "sha256:" + "f" * 64
    target.write_text(
        text.replace(text.split('schema_hash: "')[1].split('"')[0], stale),
        encoding="utf-8",
    )
    findings = validate_tree(kb_dir, snaps)
    assert any(f.check == "provenance" and "schema_hash" in f.message for f in findings)


def test_kb5_broken_relative_link(kb):
    kb_dir, _ = kb
    (kb_dir / "systems/supabase/_notes.md").write_text(
        "see [ghost](public/ghost.schema.md)\n", encoding="utf-8"
    )
    findings = validate_tree(kb_dir)
    assert any(f.check == "KB-5" and "no such file" in f.message for f in findings)


def test_kb5_broken_anchor(kb):
    kb_dir, _ = kb
    (kb_dir / "systems/supabase/_notes.md").write_text(
        "ok [cols](public/orders.schema.md#columns) "
        "bad [x](public/orders.schema.md#no-such-heading)\n",
        encoding="utf-8",
    )
    findings = validate_tree(kb_dir)
    assert [f for f in findings if f.check == "KB-5"] == [
        f for f in findings if "no-such-heading" in f.message
    ]
    assert any(f.check == "KB-5" for f in findings)


def test_kb5_same_file_anchor_and_backticked_headings(kb):
    kb_dir, _ = kb
    # heading with inline code slugs per GitHub: backticks/dots dropped
    (kb_dir / "systems/supabase/_notes.md").write_text(
        "# About `supabase.public`\n\n[up](#about-supabasepublic)\n",
        encoding="utf-8",
    )
    assert validate_tree(kb_dir) == []


def test_kb5_external_and_fenced_links_ignored(kb):
    kb_dir, _ = kb
    (kb_dir / "systems/supabase/_notes.md").write_text(
        "[docs](https://example.com/x) [mail](mailto:a@b.c)\n"
        # protocol-relative external URL — appears verbatim in GA4
        # metadata descriptions (S-8), must not read as an intra-KB path
        "[aip](//google.aip.dev/122)\n\n"
        "```sql\n-- [not a link](nowhere.md)\n```\n",
        encoding="utf-8",
    )
    assert validate_tree(kb_dir) == []


def test_kb5_escape_and_absolute_links_flagged(kb):
    kb_dir, _ = kb
    (kb_dir / "systems/supabase/_notes.md").write_text(
        "[out](../../../etc/passwd) [abs](/etc/passwd)\n", encoding="utf-8"
    )
    messages = [f.message for f in validate_tree(kb_dir) if f.check == "KB-5"]
    assert any("escapes the KB root" in m for m in messages)
    assert any("absolute link" in m for m in messages)


def test_kb5_skips_dot_directories(kb):
    kb_dir, _ = kb
    hidden = kb_dir / ".contextlayer"
    hidden.mkdir()
    (hidden / "notes.md").write_text("[broken](nowhere.md)\n", encoding="utf-8")
    assert validate_tree(kb_dir) == []


def test_cli_exit_codes(kb):
    kb_dir, _ = kb
    snapshot_args = []
    for name in THREE:
        snapshot_args += ["--snapshot", str(FIXTURES_DIR / name)]
    assert main([str(kb_dir), *snapshot_args]) == 0
    (kb_dir / "faults").mkdir()
    assert main([str(kb_dir)]) == 1
