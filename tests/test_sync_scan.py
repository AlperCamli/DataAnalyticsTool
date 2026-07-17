"""Contamination scan (lineage.scan) — KB §6 steps 1–5, formats §3.4 walk.

Covers the deliverable's named walk cases: declared-dependency hit,
graph-downstream hit at depth > 1, additive→stale, and the
undeclared-reference grep, plus determinism and the finalized-input
guard. KB trees are built per test; diffs follow the documented
`snapshot.diff` output shape post `lineage.severity`.
"""

import json
from pathlib import Path

import pytest

from lineage.graph import edge_id
from lineage.scan import ScanError, contamination_walk, main, scan

SYSTEM = "drill"

E_ORDERS_TOTALS = edge_id("drill.shop.orders", "drill.reporting.v_totals", "aggregate")
E_TOTALS_NET = edge_id("drill.reporting.v_totals", "drill.reporting.v_net", "derive")

GRAPH = {
    "graph_version": "1",
    "nodes": [
        {"id": "drill.shop.orders", "node_kind": "table", "resolved": True,
         "doc": "systems/drill/shop/orders.schema.md"},
        {"id": "drill.reporting.v_totals", "node_kind": "view", "resolved": True,
         "doc": "systems/drill/reporting/v_totals.schema.md"},
        {"id": "drill.reporting.v_net", "node_kind": "view", "resolved": True,
         "doc": "systems/drill/reporting/v_net.schema.md"},
    ],
    "edges": [
        {"id": E_ORDERS_TOTALS, "source": "drill.shop.orders",
         "target": "drill.reporting.v_totals", "operation": "aggregate",
         "evidence": [{"tier": "sql-parse", "ref": "view-def sha256:aa"}],
         "trust": "sql-parse"},
        {"id": E_TOTALS_NET, "source": "drill.reporting.v_totals",
         "target": "drill.reporting.v_net", "operation": "derive",
         "evidence": [{"tier": "sql-parse", "ref": "view-def sha256:bb"}],
         "trust": "sql-parse"},
    ],
}


def _identity(kind, schema, name):
    return {"kind": kind, "schema": schema, "name": name}


def finalized_diff(*, removed=(), breaking_changed=(), additive_changed=(), added=()):
    return {
        "system": SYSTEM,
        "empty": False,
        "added": [{"identity": i, "classification": "added", "severity": "additive"}
                  for i in added],
        "removed": [{"identity": i, "classification": "removed", "severity": "breaking"}
                    for i in removed],
        "changed_structural": [
            {"identity": i, "classification": "changed_structural",
             "severity": "breaking",
             "sub_diffs": [{"change": "column_removed", "severity": "breaking",
                            "detail": {"column": "discount", "type": "numeric",
                                       "ordinal": 4}}]}
            for i in breaking_changed
        ] + [
            {"identity": i, "classification": "changed_structural",
             "severity": "additive",
             "sub_diffs": [{"change": "column_added", "severity": "additive",
                            "detail": {"column": "note", "type": "text",
                                       "nullable": True, "ordinal": 5}}]}
            for i in additive_changed
        ],
        "changed_metadata_only": [],
        "unchanged": [],
        "skipped_unknown_kinds": [],
        "source_properties_changed": False,
        "severity_finalized": True,
    }


def write_doc(kb: Path, rel: str, fm_lines: list[str], body: str = "Body.\n"):
    path = kb / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + "\n".join(fm_lines) + "\n---\n\n" + body,
                    encoding="utf-8")


def human_object(kb: Path, rel: str, obj: str, status: str = "verified",
                 depends_on: list[str] | None = None, body: str = "Body.\n"):
    lines = [
        "doc_class: human-object",
        f"object: {obj}",
        'written_against_schema_hash: "sha256:' + "0" * 64 + '"',
        f"status: {status}",
    ]
    if depends_on is not None:
        lines.append("depends_on:")
        lines.extend(f"  - {d}" for d in depends_on)
    lines.append("contamination: null")
    write_doc(kb, rel, lines, body)


def machine_object(kb: Path, rel: str, obj: str, kind: str = "table"):
    write_doc(kb, rel, [
        "doc_class: machine-object",
        f"object: {obj}",
        f"kind: {kind}",
        'schema_hash: "sha256:' + "0" * 64 + '"',
        "generated_at: 2026-07-01",
        "source_mode: ddl-file",
        'snapshot_version: "1"',
        "status: machine",
    ])


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    root = tmp_path / "kb"
    root.mkdir()
    machine_object(root, "systems/drill/shop/orders.schema.md", "drill.shop.orders")
    machine_object(root, "systems/drill/shop/order_items.schema.md",
                   "drill.shop.order_items")
    machine_object(root, "systems/drill/reporting/v_totals.schema.md",
                   "drill.reporting.v_totals", kind="view")
    machine_object(root, "systems/drill/reporting/v_net.schema.md",
                   "drill.reporting.v_net", kind="view")
    return root


def test_declared_dependency_hit(kb):
    human_object(kb, "systems/drill/shop/sessions_notes.md", "drill.shop.sessions_notes",
                 depends_on=["drill.shop.legacy_sessions"])
    result = scan(kb, [finalized_diff(
        removed=[_identity("table", "shop", "legacy_sessions")])], GRAPH)
    [hit] = result["contaminated"]
    assert hit["doc"] == "systems/drill/shop/sessions_notes.md"
    assert hit["contamination"] == {
        "object": "drill.shop.legacy_sessions",
        "change": "removed",
        "detail": "object removed from snapshot",
    }
    assert hit["status_was"] == "verified"


def test_graph_downstream_hit_at_depth_two(kb):
    write_doc(kb, "metrics/net-sales.md", [
        "doc_class: metric",
        "status: verified",
        "depends_on:",
        "  - drill.reporting.v_net",
    ])
    result = scan(kb, [finalized_diff(
        breaking_changed=[_identity("table", "shop", "orders")])], GRAPH)
    hit = next(c for c in result["contaminated"] if c["doc"] == "metrics/net-sales.md")
    assert hit["contamination"]["object"] == "drill.shop.orders"
    assert hit["contamination"]["path"] == [E_ORDERS_TOTALS, E_TOTALS_NET]


def test_walk_flags_human_sibling_of_reached_node(kb):
    # v_totals is reached at depth 1; its human sibling declares nothing,
    # but the machine roster makes the object an implicit dependency and
    # the node's `doc` link reaches it too (formats §3.4).
    human_object(kb, "systems/drill/reporting/v_totals.md", "drill.reporting.v_totals")
    result = scan(kb, [finalized_diff(
        breaking_changed=[_identity("table", "shop", "orders")])], GRAPH)
    hit = next(c for c in result["contaminated"]
               if c["doc"] == "systems/drill/reporting/v_totals.md")
    assert hit["contamination"]["path"] == [E_ORDERS_TOTALS]


def test_direct_reason_ranks_before_walk_reason(kb):
    # doc depends on both the breaking object itself and a downstream node
    human_object(kb, "systems/drill/reporting/v_net.md", "drill.reporting.v_net",
                 depends_on=["drill.shop.orders"])
    result = scan(kb, [finalized_diff(
        breaking_changed=[_identity("table", "shop", "orders")])], GRAPH)
    hit = next(c for c in result["contaminated"]
               if c["doc"] == "systems/drill/reporting/v_net.md")
    assert hit["contamination"]["object"] == "drill.shop.orders"
    assert "path" not in hit["contamination"]  # the declared (direct) reason wins
    # one reason per (doc, breaking object): the direct route subsumes the walk
    assert len(hit["reasons"]) == 1


def test_additive_to_stale_only_for_verified(kb):
    human_object(kb, "systems/drill/shop/order_items.md", "drill.shop.order_items",
                 status="verified")
    human_object(kb, "systems/drill/shop/items_draft.md", "drill.shop.items_draft",
                 status="draft", depends_on=["drill.shop.order_items"])
    result = scan(kb, [finalized_diff(
        additive_changed=[_identity("table", "shop", "order_items")])], GRAPH)
    assert result["contaminated"] == []
    [stale] = result["stale"]
    assert stale["doc"] == "systems/drill/shop/order_items.md"
    assert stale["objects"] == ["drill.shop.order_items"]


def test_contamination_wins_over_stale(kb):
    human_object(kb, "systems/drill/shop/order_items.md", "drill.shop.order_items",
                 depends_on=["drill.shop.legacy_sessions"])
    result = scan(kb, [finalized_diff(
        removed=[_identity("table", "shop", "legacy_sessions")],
        additive_changed=[_identity("table", "shop", "order_items")])], GRAPH)
    assert [c["doc"] for c in result["contaminated"]] == \
        ["systems/drill/shop/order_items.md"]
    assert result["stale"] == []


def test_undeclared_reference_grep(kb):
    human_object(kb, "systems/drill/shop/order_items.md", "drill.shop.order_items",
                 body="Joins against `drill.shop.legacy_sessions` for history.\n")
    (kb / "conventions.md").write_text(
        "Mind `drill.shop.legacy_sessions (table)` when querying.\n",
        encoding="utf-8")
    result = scan(kb, [finalized_diff(
        removed=[_identity("table", "shop", "legacy_sessions")])], GRAPH)
    assert result["undeclared_references"] == [
        {"doc": "conventions.md", "object": "drill.shop.legacy_sessions"},
        {"doc": "systems/drill/shop/order_items.md",
         "object": "drill.shop.legacy_sessions"},
    ]
    # a declared dependent never lands in the undeclared list
    human_object(kb, "systems/drill/shop/declared.md", "drill.shop.declared",
                 depends_on=["drill.shop.legacy_sessions"],
                 body="Uses `drill.shop.legacy_sessions` daily.\n")
    result = scan(kb, [finalized_diff(
        removed=[_identity("table", "shop", "legacy_sessions")])], GRAPH)
    assert "systems/drill/shop/declared.md" not in [
        u["doc"] for u in result["undeclared_references"]]


def test_entity_maps_are_a_declaration_surface(kb):
    write_doc(kb, "entities/customer.md", [
        "doc_class: entity",
        "status: verified",
        "maps:",
        '  - { object: "drill.shop.orders", role: system-of-record, keys: [id] }',
        "depends_on:",
        "  - drill.shop.orders",
    ])
    result = scan(kb, [finalized_diff(
        breaking_changed=[_identity("table", "shop", "orders")])], GRAPH)
    assert "entities/customer.md" in [c["doc"] for c in result["contaminated"]]


def test_external_dependencies_are_excluded(kb):
    write_doc(kb, "entities/payment.md", [
        "doc_class: entity",
        "status: verified",
        "depends_on:",
        '  - { object: "drill.shop.orders", external: true }',
    ])
    result = scan(kb, [finalized_diff(
        breaking_changed=[_identity("table", "shop", "orders")])], GRAPH)
    assert result["contaminated"] == []


def test_unfinalized_diff_is_refused(kb):
    diff = finalized_diff(removed=[_identity("table", "shop", "legacy_sessions")])
    del diff["severity_finalized"]
    with pytest.raises(ScanError):
        scan(kb, [diff], GRAPH)


def test_walk_handles_cycles_and_is_min_hop():
    e_ab = edge_id("a", "b", "derive")
    e_bc = edge_id("b", "c", "derive")
    e_ca = edge_id("c", "a", "derive")
    e_ac = edge_id("a", "c", "derive")
    graph = {"nodes": [], "edges": [
        {"id": e_ab, "source": "a", "target": "b", "operation": "derive"},
        {"id": e_bc, "source": "b", "target": "c", "operation": "derive"},
        {"id": e_ca, "source": "c", "target": "a", "operation": "derive"},
        {"id": e_ac, "source": "a", "target": "c", "operation": "derive"},
    ]}
    paths = contamination_walk(graph, "a")
    assert paths["a"] == []
    assert paths["b"] == [e_ab]
    assert paths["c"] == [e_ac]  # min-hop, not via b


def test_scan_is_deterministic(kb):
    human_object(kb, "systems/drill/shop/order_items.md", "drill.shop.order_items",
                 depends_on=["drill.shop.legacy_sessions", "drill.shop.orders"])
    diffs = [finalized_diff(
        removed=[_identity("table", "shop", "legacy_sessions")],
        breaking_changed=[_identity("table", "shop", "orders")])]
    first = json.dumps(scan(kb, diffs, GRAPH), sort_keys=True)
    second = json.dumps(scan(kb, diffs, GRAPH), sort_keys=True)
    assert first == second


def test_cli_round_trip(kb, tmp_path):
    human_object(kb, "systems/drill/shop/sessions_notes.md",
                 "drill.shop.sessions_notes",
                 depends_on=["drill.shop.legacy_sessions"])
    diff_file = tmp_path / "diff.json"
    graph_file = tmp_path / "graph.json"
    out_file = tmp_path / "scan.json"
    diff_file.write_text(json.dumps(finalized_diff(
        removed=[_identity("table", "shop", "legacy_sessions")])), encoding="utf-8")
    graph_file.write_text(json.dumps(GRAPH), encoding="utf-8")
    code = main(["--kb", str(kb), "--graph", str(graph_file),
                 "--diff", str(diff_file), "--out", str(out_file)])
    assert code == 0
    result = json.loads(out_file.read_text(encoding="utf-8"))
    assert [c["doc"] for c in result["contaminated"]] == \
        ["systems/drill/shop/sessions_notes.md"]
