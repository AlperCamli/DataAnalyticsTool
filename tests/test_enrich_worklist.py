"""The enrich skill's contamination work list (S1c, D-119.2b).

Deterministic assembly only: the tool joins markers to current facts and
orders by severity. It classifies nothing — the tests below pin that the
*evidence* arrives intact and in the right order, which is what a session
needs before it can classify anything.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCENARIO_KB = REPO / "tools" / "scenarios" / "triage-kb"

_spec = importlib.util.spec_from_file_location(
    "enrich_worklist", REPO / "core" / "skills" / "enrich" / "worklist.py")
worklist_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(worklist_mod)


@pytest.fixture
def staged() -> dict:
    return worklist_mod.worklist(SCENARIO_KB)


def test_the_three_classes_arrive_with_their_evidence(staged):
    docs = {d["doc"]: d for d in staged["docs"]}
    assert staged["contaminated"] == 3

    confirms = docs["systems/triage/shop/exports.md"]
    assert confirms["cause"] == "triage.shop.exports"
    # The CHECK constraints are the evidence the confirms/contradicts call
    # is made on — without them a session is judging prose against nothing.
    assert any("processing" in c for c in confirms["cause_facts"]["checks"])
    assert confirms["cause_facts"]["schema_hash"].startswith("sha256:")

    regrounding = docs["systems/triage/shop/imports.md"]
    assert "reviewed" in " ".join(regrounding["cause_facts"]["checks"])

    missing = docs["systems/triage/shop/orders.md"]
    assert missing["dependency_unresolved"] == ["triage.shop.legacy_carts"]


def test_unresolved_dependencies_sort_first(staged):
    assert staged["docs"][0]["doc"] == "systems/triage/shop/orders.md"


def test_changed_columns_are_the_constrained_ones_not_every_column(staged):
    docs = {d["doc"]: d for d in staged["docs"]}
    exports = docs["systems/triage/shop/exports.md"]
    # `created_at` and `id` exist on the table and moved not at all; a work
    # list that named them would drown the two that did.
    assert exports["changed_columns"] == ["format", "status"]
    assert "created_at" not in exports["mentions"]


def test_a_doc_silent_about_the_change_is_visible_as_such(tmp_path):
    snap = json.loads((SCENARIO_KB / ".contextlayer" / "snapshots" / "triage.json").read_text())
    (tmp_path / ".contextlayer" / "snapshots").mkdir(parents=True)
    (tmp_path / ".contextlayer" / "snapshots" / "triage.json").write_text(json.dumps(snap))
    doc = tmp_path / "systems" / "triage" / "shop" / "quiet.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(
        "---\ndoc_class: human-object\nobject: triage.shop.quiet\n"
        "status: contaminated\nlast_verified: null\n"
        'contamination: {object: "triage.shop.exports", change: "stat_changed", '
        'detail: "stat_changed: checks"}\ndepends_on:\n  - triage.shop.exports\n---\n\n'
        "# quiet\n\nThis doc says nothing about export formats or states.\n",
        encoding="utf-8")
    result = worklist_mod.worklist(tmp_path)
    (entry,) = result["docs"]
    assert entry["mentions"] == []  # names neither the object nor a changed column


def test_previously_verified_outranks_a_draft(tmp_path):
    snap = json.loads((SCENARIO_KB / ".contextlayer" / "snapshots" / "triage.json").read_text())
    (tmp_path / ".contextlayer" / "snapshots").mkdir(parents=True)
    (tmp_path / ".contextlayer" / "snapshots" / "triage.json").write_text(json.dumps(snap))
    for name, last_verified in (("a_draft", "null"), ("b_certified", '"2026-08-01 (a.demir)"')):
        doc = tmp_path / f"{name}.md"
        doc.write_text(
            f"---\ndoc_class: human-object\nobject: triage.shop.{name}\n"
            f"status: contaminated\nlast_verified: {last_verified}\n"
            'contamination: {object: "triage.shop.exports", change: "stat_changed", '
            'detail: "stat_changed: checks"}\ndepends_on:\n  - triage.shop.exports\n---\n\nbody\n',
            encoding="utf-8")
    result = worklist_mod.worklist(tmp_path)
    assert [d["doc"] for d in result["docs"]] == ["b_certified.md", "a_draft.md"]


def test_batches_keep_one_cause_together_and_cap_at_ten():
    docs = ([{"doc": f"a{i}.md", "cause": "x"} for i in range(12)] +
            [{"doc": f"b{i}.md", "cause": "y"} for i in range(3)])
    batches = worklist_mod.batches(docs)
    assert [len(b) for b in batches] == [10, 5]  # the x-remainder packs with y, unsplit
    assert {d["cause"] for d in batches[0]} == {"x"}
    assert {d["cause"] for d in batches[1]} == {"x", "y"}


def test_report_path_ordering_says_when_it_is_unavailable(staged):
    # The staged KB has no golden suite; the tool must say so rather than
    # silently ranking every doc as off the report path.
    assert "no golden suite" in staged["report_path_note"]


def test_the_pilot_kb_work_list_is_stable_and_ordered():
    kb = Path.home() / "Desktop" / "kb"
    if not (kb / ".contextlayer" / "snapshots").is_dir():
        pytest.skip("no pilot KB clone on this machine")
    first, second = worklist_mod.worklist(kb), worklist_mod.worklist(kb)
    assert [d["doc"] for d in first["docs"]] == [d["doc"] for d in second["docs"]]
    for a, b in zip(first["docs"], first["docs"][1:]):
        # severity ordering, in the tool's own key order
        assert (not a["dependency_unresolved"], not a["was_verified"], not a["on_report_path"]) <= \
               (not b["dependency_unresolved"], not b["was_verified"], not b["on_report_path"])
