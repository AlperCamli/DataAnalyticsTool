"""Severity finalization (lineage.severity) — snapshot §7 note ³.

The diff shapes here are hand-built to the documented `snapshot.diff`
output contract; the drill fixture e2e (SO-4) exercises the real
diff → severity → scan chain end to end.
"""

import json

import pytest

from lineage.graph import edge_id
from lineage.severity import FinalizeError, finalize_severity, main

SYSTEM = "drill"
VIEW_FQN = "drill.reporting.v_totals"


def _diff(sub_diffs):
    return {
        "system": SYSTEM,
        "empty": False,
        "added": [],
        "removed": [],
        "changed_structural": [
            {
                "identity": {"kind": "view", "schema": "reporting", "name": "v_totals"},
                "classification": "changed_structural",
                "severity": "breaking",
                "sub_diffs": sub_diffs,
            }
        ],
        "changed_metadata_only": [],
        "unchanged": [],
        "skipped_unknown_kinds": [],
        "source_properties_changed": False,
    }


def _definition_sub():
    return {
        "change": "definition_changed",
        "severity": "breaking",
        "detail": {"stat": "definition", "from": "old", "to": "new"},
        "downgradable": True,
    }


def _graph(columns):
    eid = edge_id("drill.shop.orders", VIEW_FQN, "aggregate")
    return {
        "nodes": [{"id": "drill.shop.orders"}, {"id": VIEW_FQN}],
        "edges": [
            {
                "id": eid,
                "source": "drill.shop.orders",
                "target": VIEW_FQN,
                "operation": "aggregate",
                "columns": columns,
                "evidence": [{"tier": "sql-parse", "ref": "view-def sha256:aaaa"}],
                "trust": "sql-parse",
            }
        ],
    }


def test_downgrades_when_output_and_mappings_unchanged():
    old = _graph([{"from": ["net"], "to": "net_total"}])
    new = _graph([{"from": ["net"], "to": "net_total"}])
    # evidence refs differ across a definition edit — must not block
    new["edges"][0]["evidence"] = [{"tier": "sql-parse", "ref": "view-def sha256:bbbb"}]
    out = finalize_severity(_diff([_definition_sub()]), old, new)
    obj = out["changed_structural"][0]
    sub = obj["sub_diffs"][0]
    assert sub["severity"] == "additive-with-note"
    assert sub["downgraded"] == "snapshot-§7-note-3"
    assert "downgradable" not in sub
    assert obj["severity"] == "additive-with-note"
    assert out["severity_finalized"] is True


def test_no_downgrade_when_mappings_changed():
    old = _graph([{"from": ["net"], "to": "net_total"}])
    new = _graph([{"from": ["net", "tax"], "to": "net_total"}])
    out = finalize_severity(_diff([_definition_sub()]), old, new)
    obj = out["changed_structural"][0]
    assert obj["sub_diffs"][0]["severity"] == "breaking"
    assert "downgraded" not in obj["sub_diffs"][0]
    assert obj["severity"] == "breaking"


def test_no_downgrade_when_column_set_changed():
    same = _graph([{"from": ["net"], "to": "net_total"}])
    column_added = {
        "change": "column_added",
        "severity": "additive",
        "detail": {"column": "item_count", "type": "bigint", "nullable": True, "ordinal": 3},
    }
    out = finalize_severity(_diff([_definition_sub(), column_added]), same, same)
    obj = out["changed_structural"][0]
    definition = next(s for s in obj["sub_diffs"] if s["change"] == "definition_changed")
    assert definition["severity"] == "breaking"
    assert obj["severity"] == "breaking"


def test_other_breaking_subs_keep_object_breaking_despite_downgrade():
    same = _graph([{"from": ["net"], "to": "net_total"}])
    key_removed = {
        "change": "key_removed",
        "severity": "breaking",
        "detail": {"key": "unique", "columns": ["sku"]},
    }
    out = finalize_severity(_diff([_definition_sub(), key_removed]), same, same)
    obj = out["changed_structural"][0]
    definition = next(s for s in obj["sub_diffs"] if s["change"] == "definition_changed")
    assert definition["severity"] == "additive-with-note"
    assert obj["severity"] == "breaking"


def test_missing_graphs_with_downgradable_sub_is_an_error():
    with pytest.raises(FinalizeError):
        finalize_severity(_diff([_definition_sub()]), None, None)


def test_pass_through_without_downgradable_subs():
    diff = _diff(
        [{"change": "column_removed", "severity": "breaking",
          "detail": {"column": "net", "type": "numeric", "ordinal": 2}}]
    )
    out = finalize_severity(diff, None, None)
    assert out["severity_finalized"] is True
    assert out["changed_structural"][0]["severity"] == "breaking"


def test_cli_round_trip(tmp_path):
    diff_file = tmp_path / "diff.json"
    old_file = tmp_path / "old.json"
    new_file = tmp_path / "new.json"
    out_file = tmp_path / "final.json"
    diff_file.write_text(json.dumps(_diff([_definition_sub()])), encoding="utf-8")
    graph = _graph([{"from": ["net"], "to": "net_total"}])
    old_file.write_text(json.dumps(graph), encoding="utf-8")
    new_file.write_text(json.dumps(graph), encoding="utf-8")
    code = main([str(diff_file), "--old-graph", str(old_file),
                 "--new-graph", str(new_file), "--out", str(out_file)])
    assert code == 0
    final = json.loads(out_file.read_text(encoding="utf-8"))
    assert final["severity_finalized"] is True
    assert final["changed_structural"][0]["severity"] == "additive-with-note"


def test_cli_requires_graph_pair(tmp_path):
    diff_file = tmp_path / "diff.json"
    diff_file.write_text(json.dumps(_diff([])), encoding="utf-8")
    assert main([str(diff_file), "--old-graph", str(diff_file)]) == 2
