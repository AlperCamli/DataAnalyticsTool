"""Front-matter status writer (generator.statuses) — KB §6/KB-4.

The invariant under test: only the `status:` line and the
`contamination:` field ever change; every other byte of the file —
including bodies containing `---` fences and `status:`-looking text —
round-trips exactly.
"""

import json

import pytest

from generator import frontmatter
from generator.statuses import StatusWriteError, apply_all, apply_instruction, main

DOC = """---
doc_class: human-object
object: drill.shop.customers
written_against_schema_hash: "sha256:%s"
status: verified
last_verified: "2026-07-01 (a.demir)"
sources:
  - "customer doc: crm.md"
depends_on:
  - drill.shop.orders
contamination: null
purpose: "One row per customer."
---

## Purpose

Tracks customers. Note the tricky bits below:

---

status: this line is body text, not front-matter
contamination: also body text
""" % ("0" * 64)

CONTAMINATION = {
    "object": "drill.shop.orders",
    "change": "column_removed",
    "detail": "column_removed: discount",
    "path": ["sha256:" + "a" * 64],
}


def test_contaminate_round_trip():
    edited = apply_instruction(
        DOC, {"doc": "x", "status": "contaminated", "contamination": CONTAMINATION}
    )
    fm, body = frontmatter.split(edited)
    old_fm, old_body = frontmatter.split(DOC)
    assert body == old_body  # KB-4: nothing below the fence, byte-for-byte
    assert fm["status"] == "contaminated"
    assert fm["contamination"] == CONTAMINATION
    # every other front-matter field survives untouched
    for key, value in old_fm.items():
        if key not in ("status", "contamination"):
            assert fm[key] == value
    # and untouched *lines* are byte-identical, not merely re-emitted
    for line in ("written_against_schema_hash", "purpose:", "last_verified"):
        original = next(l for l in DOC.splitlines() if l.startswith(line))
        assert original in edited.splitlines()


def test_stale_leaves_contamination_untouched():
    edited = apply_instruction(DOC, {"doc": "x", "status": "stale"})
    assert "status: stale" in edited
    assert "contamination: null" in edited
    fm, _ = frontmatter.split(edited)
    assert fm["contamination"] is None


def test_insertion_when_doc_never_carried_contamination():
    doc = DOC.replace("contamination: null\n", "")
    edited = apply_instruction(
        doc, {"doc": "x", "status": "contaminated", "contamination": CONTAMINATION}
    )
    fm, body = frontmatter.split(edited)
    assert fm["contamination"] == CONTAMINATION
    assert body == frontmatter.split(doc)[1]


def test_block_style_contamination_is_replaced_whole():
    doc = DOC.replace(
        "contamination: null\n",
        'contamination:\n  object: "old.fqn"\n  change: removed\n',
    )
    edited = apply_instruction(
        doc, {"doc": "x", "status": "verified", "contamination": None}
    )
    fm, _ = frontmatter.split(edited)
    assert fm["contamination"] is None
    assert "old.fqn" not in edited


def test_repair_direction_clears_to_null():
    contaminated = apply_instruction(
        DOC, {"doc": "x", "status": "contaminated", "contamination": CONTAMINATION}
    )
    restored = apply_instruction(
        contaminated, {"doc": "x", "status": "verified", "contamination": None}
    )
    assert restored == DOC


def test_missing_status_line_fails_loudly():
    doc = "---\ndoc_class: human-notes\n---\nBody.\n"
    with pytest.raises(StatusWriteError):
        apply_instruction(doc, {"doc": "x", "status": "stale"})


def test_no_front_matter_fails_loudly():
    with pytest.raises(StatusWriteError):
        apply_instruction("Just a body.\n", {"doc": "x", "status": "stale"})


def test_apply_all_is_all_or_nothing(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    good = kb / "good.md"
    good.write_text(DOC, encoding="utf-8")
    bad = kb / "bad.md"
    bad.write_text("no front-matter\n", encoding="utf-8")
    with pytest.raises(StatusWriteError):
        apply_all(kb, [
            {"doc": "good.md", "status": "stale"},
            {"doc": "bad.md", "status": "stale"},
        ])
    assert good.read_text(encoding="utf-8") == DOC  # untouched


def test_apply_all_reports_unchanged(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "doc.md").write_text(DOC, encoding="utf-8")
    result = apply_all(kb, [{"doc": "doc.md", "status": "verified"}])
    assert result == {"edited": [], "unchanged": ["doc.md"]}
    result = apply_all(kb, [{"doc": "doc.md", "status": "stale"}])
    assert result == {"edited": ["doc.md"], "unchanged": []}


def test_cli_round_trip(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "doc.md").write_text(DOC, encoding="utf-8")
    instructions = tmp_path / "instructions.json"
    instructions.write_text(json.dumps(
        [{"doc": "doc.md", "status": "contaminated", "contamination": CONTAMINATION}]
    ), encoding="utf-8")
    assert main(["--kb", str(kb), str(instructions)]) == 0
    fm, _ = frontmatter.split((kb / "doc.md").read_text(encoding="utf-8"))
    assert fm["status"] == "contaminated"
    assert fm["contamination"] == CONTAMINATION
