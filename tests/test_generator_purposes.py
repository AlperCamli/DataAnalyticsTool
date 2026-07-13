"""D-49 purpose merge: enrichment front-matter flows into machine renders
(Purpose slots, `—` when absent), purpose-only re-renders keep
`generated_at` (KB §4.1) even across advanced capture dates, KB-8 catches
enrichment PRs missing their implied re-renders, KB-10 warns on dangling
purpose keys, and `_notes.md` front-matter validates as human-notes.
"""

import json

from generator.render import render_tree
from generator.validate import main, validate_tree
from tests.conftest import changed_paths, load_fixture, mutate, tree_bytes

ORDERS_DOC = "systems/supabase/public/orders.schema.md"
SCHEMA_INDEX = "systems/supabase/public/index.md"
SYSTEM_INDEX = "systems/supabase/index.md"


def orders_hash(snap: dict) -> str:
    return next(o["schema_hash"] for o in snap["objects"] if o["name"] == "orders")


def human_doc(
    doc_class: str,
    obj: str,
    schema_hash: str,
    purpose: str | None = None,
    purpose_map: tuple[str, dict] | None = None,
) -> str:
    lines = [
        "---",
        f"doc_class: {doc_class}",
        f"object: {obj}",
        f'written_against_schema_hash: "{schema_hash}"',
        "status: draft",
    ]
    if purpose is not None:
        lines.append(f'purpose: "{purpose}"')
    if purpose_map is not None:
        key, mapping = purpose_map
        lines.append(f"{key}:")
        for k, v in mapping.items():
            lines.append(f'  {json.dumps(k)}: "{v}"')
    lines += ["---", "", "Body.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# merge behavior (D-49.2)


def test_column_purpose_appears_and_reverts_to_dash(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    assert "| Purpose |" in (tmp_path / ORDERS_DOC).read_text()

    human = tmp_path / "systems/supabase/public/orders.md"
    human.write_text(
        human_doc(
            "human-object",
            "supabase.public.orders",
            orders_hash(snap),
            purpose="One row per checkout.",
            purpose_map=("column_purposes", {"status": "Order lifecycle state."}),
        ),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)
    doc = (tmp_path / ORDERS_DOC).read_text()
    assert "| Order lifecycle state. |" in doc
    assert "One row per checkout." not in doc  # object purpose is the index's
    index = (tmp_path / SCHEMA_INDEX).read_text()
    assert "| One row per checkout. |" in index

    human.write_text(
        human_doc("human-object", "supabase.public.orders", orders_hash(snap)),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)
    assert "Order lifecycle state." not in (tmp_path / ORDERS_DOC).read_text()
    assert "One row per checkout." not in (tmp_path / SCHEMA_INDEX).read_text()
    # the slot renders the absent-fact marker again
    status_row = next(
        line
        for line in (tmp_path / ORDERS_DOC).read_text().splitlines()
        if line.startswith("| 3 | `status` |")
    )
    assert status_row.endswith("| — |")


def test_group_purposes_render_in_group_doc_and_system_index(tmp_path):
    snap = load_fixture("ga4.json")
    render_tree([snap], tmp_path)
    (tmp_path / "systems/ga4/metrics.md").write_text(
        human_doc(
            "human-group",
            "ga4.metrics",
            "sha256:" + "0" * 64,
            purpose="Traffic and revenue measures.",
            purpose_map=(
                "object_purposes",
                {"ga4.standard.sessions": "Visit count; the denominator metric."},
            ),
        ),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)
    group_doc = (tmp_path / "systems/ga4/metrics.schema.md").read_text()
    assert "| Purpose | Visit count; the denominator metric. |" in group_doc
    system_index = (tmp_path / "systems/ga4/index.md").read_text()
    assert "| Traffic and revenue measures. |" in system_index
    # members without an object_purposes entry keep the absent marker
    assert "| Purpose | — |" in group_doc


def test_schema_notes_purpose_renders_in_system_index(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    (tmp_path / "systems/supabase/public/_notes.md").write_text(
        '---\ndoc_class: human-notes\npurpose: "Core commerce schema."\n---\n\nNarrative.\n',
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)
    assert "| Core commerce schema. |" in (tmp_path / SYSTEM_INDEX).read_text()


# --------------------------------------------------------------------------
# generated_at (D-49.4): purpose-driven re-renders never restamp


def test_purpose_only_change_keeps_generated_at_across_newer_capture(tmp_path):
    snap = load_fixture("supabase-ddl.json")  # captured 2026-07-11
    render_tree([snap], tmp_path)
    human = tmp_path / "systems/supabase/public/orders.md"
    human.write_text(
        human_doc("human-object", "supabase.public.orders", orders_hash(snap)),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)  # hot/stub flip lands, still 07-11

    # a recaptured-but-unchanged snapshot: renders untouched, stamps stay
    newer = load_fixture("supabase-ddl.json")
    newer["captured_at"] = "2026-07-12T02:00:00Z"
    render_tree([newer], tmp_path)
    before = tree_bytes(tmp_path)
    assert b"generated_at: 2026-07-11" in before[ORDERS_DOC]

    # the purpose-only edit, rendered against the newer snapshot
    human.write_text(
        human_doc(
            "human-object",
            "supabase.public.orders",
            orders_hash(snap),
            purpose="One row per checkout.",
            purpose_map=("column_purposes", {"status": "Order lifecycle state."}),
        ),
        encoding="utf-8",
    )
    render_tree([newer], tmp_path)
    after = tree_bytes(tmp_path)

    assert changed_paths(before, after) == {
        "systems/supabase/public/orders.md",  # the human edit itself
        ORDERS_DOC,
        SCHEMA_INDEX,
    }
    for rel in (ORDERS_DOC, SCHEMA_INDEX):
        assert b"generated_at: 2026-07-11" in after[rel], rel
        assert b"2026-07-12" not in after[rel], rel
    assert b"Order lifecycle state." in after[ORDERS_DOC]
    assert b"One row per checkout." in after[SCHEMA_INDEX]

    # KB-8 fixed point holds with enrichment present
    render_tree([newer], tmp_path)
    assert tree_bytes(tmp_path) == after


def test_fact_change_with_purposes_present_still_restamps(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    (tmp_path / "systems/supabase/public/orders.md").write_text(
        human_doc(
            "human-object",
            "supabase.public.orders",
            orders_hash(snap),
            purpose_map=("column_purposes", {"status": "Order lifecycle state."}),
        ),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)

    def edit(obj):
        col = next(c for c in obj["columns"] if c["name"] == "total_cents")
        col["type"] = "bigint"

    edited = mutate(snap, "orders", edit)
    edited["captured_at"] = "2026-07-13T02:00:00Z"
    render_tree([edited], tmp_path)
    doc = (tmp_path / ORDERS_DOC).read_text()
    assert "generated_at: 2026-07-13" in doc  # facts changed: honest restamp
    assert "| Order lifecycle state. |" in doc  # enrichment still merged


# --------------------------------------------------------------------------
# KB-8 render consistency (D-49.3) and KB-10 dangling keys (D-49.5)


def test_kb8_blocks_enrichment_edit_without_rerender(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    assert validate_tree(tmp_path, [snap]) == []

    (tmp_path / "systems/supabase/public/orders.md").write_text(
        human_doc(
            "human-object",
            "supabase.public.orders",
            orders_hash(snap),
            purpose="One row per checkout.",
        ),
        encoding="utf-8",
    )
    findings = validate_tree(tmp_path, [snap])
    assert findings and all(f.check == "KB-8" and f.level == "error" for f in findings)
    assert {f.path for f in findings} >= {SCHEMA_INDEX}

    render_tree([snap], tmp_path)
    assert validate_tree(tmp_path, [snap]) == []


def test_kb10_dangling_column_key_warns_with_doc_and_key(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    (tmp_path / "systems/supabase/public/orders.md").write_text(
        human_doc(
            "human-object",
            "supabase.public.orders",
            orders_hash(snap),
            purpose_map=("column_purposes", {"stauts": "typo for status"}),
        ),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)  # dangling keys render nothing; tree stays consistent

    findings = validate_tree(tmp_path, [snap])
    assert [f.check for f in findings] == ["KB-10"]
    (warn,) = findings
    assert warn.level == "warn"
    assert warn.path == "systems/supabase/public/orders.md"
    assert "'stauts'" in warn.message and "supabase.public.orders" in warn.message


def test_kb10_dangling_roster_key_warns(tmp_path):
    snap = load_fixture("ga4.json")
    render_tree([snap], tmp_path)
    (tmp_path / "systems/ga4/metrics.md").write_text(
        human_doc(
            "human-group",
            "ga4.metrics",
            "sha256:" + "0" * 64,
            purpose_map=("object_purposes", {"ga4.standard.nope": "no such metric"}),
        ),
        encoding="utf-8",
    )
    render_tree([snap], tmp_path)
    findings = validate_tree(tmp_path, [snap])
    assert [f.check for f in findings] == ["KB-10"]
    assert findings[0].level == "warn"
    assert "'ga4.standard.nope'" in findings[0].message
    assert findings[0].path == "systems/ga4/metrics.md"


# --------------------------------------------------------------------------
# schemas: one-line contract, human-notes class (D-49.1)


def test_multiline_purpose_is_kb1(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    (tmp_path / "systems/supabase/public/orders.md").write_text(
        human_doc("human-object", "supabase.public.orders", orders_hash(snap)).replace(
            "status: draft", 'status: draft\npurpose: "two\\nlines"'
        ),
        encoding="utf-8",
    )
    findings = validate_tree(tmp_path)
    assert any(f.check == "KB-1" and "purpose" in f.message for f in findings)


def test_notes_front_matter_validates_as_human_notes(tmp_path):
    snap = load_fixture("supabase-ddl.json")
    render_tree([snap], tmp_path)
    notes = tmp_path / "systems/supabase/_notes.md"

    notes.write_text("no front-matter, still exempt\n", encoding="utf-8")
    assert validate_tree(tmp_path) == []

    notes.write_text(
        '---\ndoc_class: human-notes\npurpose: "The commerce estate."\n---\n\nOK.\n',
        encoding="utf-8",
    )
    assert validate_tree(tmp_path) == []

    notes.write_text(
        '---\ndoc_class: human-notes\nowner: "someone"\n---\n\nUnknown key.\n',
        encoding="utf-8",
    )
    assert any(f.check == "KB-1" for f in validate_tree(tmp_path))

    notes.write_text(
        "---\ndoc_class: human-object\nobject: x\n"
        'written_against_schema_hash: "sha256:' + "0" * 64 + '"\n'
        "status: draft\n---\n\nWrong class.\n",
        encoding="utf-8",
    )
    assert any(
        f.check == "layout" and "human-notes" in f.message
        for f in validate_tree(tmp_path)
    )


# --------------------------------------------------------------------------
# CLI: warns don't fail, snapshots auto-discovered from .contextlayer (§3)


def test_cli_autodiscovers_snapshots_and_warns_dont_fail(tmp_path, capsys):
    snap = load_fixture("supabase-ddl.json")
    kb = tmp_path / "kb"
    render_tree([snap], kb)
    snapdir = kb / ".contextlayer" / "snapshots"
    snapdir.mkdir(parents=True)
    (snapdir / "supabase.json").write_text(json.dumps(snap), encoding="utf-8")

    assert main([str(kb)]) == 0

    human = kb / "systems/supabase/public/orders.md"
    human.write_text(
        human_doc(
            "human-object",
            "supabase.public.orders",
            orders_hash(snap),
            purpose_map=("column_purposes", {"stauts": "typo"}),
        ),
        encoding="utf-8",
    )
    # unrendered enrichment: KB-8 error via the auto-discovered snapshot
    assert main([str(kb)]) == 1
    assert "[KB-8]" in capsys.readouterr().out

    render_tree([snap], kb)
    assert main([str(kb)]) == 0  # KB-10 dangling key warns, doesn't block
    out = capsys.readouterr().out
    assert "[KB-10 warn]" in out and "0 errors, 1 warning" in out
