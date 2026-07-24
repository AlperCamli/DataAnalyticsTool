"""Task 1.9 exit evidence (plan, verbatim): every DDL view's upstream
tables + column mappings resolve; get_lineage walks them.

Primary evidence runs against the connector-produced customer snapshot
(`fixtures/supabase-customer.json`, D-44 — qualified names, the D-19.2
primary path). The hand-authored 1.1 fixtures stay as the fallback-path
tests (unqualified names, D-42.7 unique-match).
"""

import json

from lineage import build_graph, get_lineage, render_graph, write_graph
from lineage.__main__ import main as lineage_cli
from lineage.graph import edge_id
from tests.conftest import (
    FIXTURES_DIR,
    graph_edge,
    graph_node,
    load_fixture,
    tree_bytes,
)

CUSTOMER = "supabase-customer.json"
ORDERS = "supabase.public.orders"
VIEW = "supabase.public.v_daily_revenue"
MATVIEW = "supabase.public.mv_user_ltv"


def customer_graph():
    return build_graph([load_fixture(CUSTOMER)])


# --- exit criterion: views resolve with column mappings ------------------------


def test_customer_view_resolves_to_upstream_table_with_mappings():
    edge = graph_edge(customer_graph(), ORDERS, VIEW)
    assert edge["id"] == edge_id(ORDERS, VIEW, "aggregate")
    assert edge["operation"] == "aggregate"
    assert edge["trust"] == "sql-parse"
    assert edge["columns"] == [
        {"from": ["created_at"], "to": "day"},
        {"from": [], "to": "order_count"},        # count(*): column-free (D-42.2)
        {"from": ["total_cents"], "to": "revenue_cents"},
    ]


def test_customer_matview_resolves_to_upstream_table_with_mappings():
    edge = graph_edge(customer_graph(), ORDERS, MATVIEW)
    assert edge["operation"] == "aggregate"
    assert edge["columns"] == [
        {"from": ["created_at"], "to": "first_order_at"},
        {"from": ["created_at"], "to": "last_order_at"},
        {"from": ["total_cents"], "to": "ltv_cents"},
        {"from": ["user_id"], "to": "user_id"},
    ]


def test_customer_nodes_resolved_with_doc_paths():
    graph = customer_graph()
    assert {n["id"] for n in graph["nodes"]} == {ORDERS, VIEW, MATVIEW}
    for fqn, kind in ((ORDERS, "table"), (VIEW, "view"), (MATVIEW, "materialized_view")):
        node = graph_node(graph, fqn)
        assert node["resolved"] is True
        assert node["node_kind"] == kind
    assert graph_node(graph, VIEW)["doc"] == (
        "systems/supabase/public/v_daily_revenue.schema.md"
    )


# --- exit criterion: get_lineage walks both directions ---------------------------


def test_walk_upstream_from_both_views():
    graph = customer_graph()
    for start in (VIEW, MATVIEW):
        result = get_lineage(graph, start, "upstream")
        assert {n["id"]: n["depth"] for n in result["nodes"]} == {start: 0, ORDERS: 1}
        assert len(result["edges"]) == 1
        assert result["edges"][0]["columns"]  # column data served verbatim
        assert result["cycles"] == []


def test_walk_downstream_from_base_table():
    result = get_lineage(customer_graph(), ORDERS, "downstream")
    assert {n["id"]: n["depth"] for n in result["nodes"]} == {
        ORDERS: 0, MATVIEW: 1, VIEW: 1,
    }
    assert len(result["edges"]) == 2


# --- determinism (FG-1) ------------------------------------------------------------


def test_same_snapshot_twice_builds_byte_identical_graph():
    assert render_graph(customer_graph()) == render_graph(customer_graph())


def test_ddl_and_live_snapshots_yield_a_byte_noop(tmp_path):
    """The 1.1 fixture pair is canonical-body-identical with differing
    captured_at (S-3/S-4): regenerating from `live` after `ddl` must
    leave graph.json byte-untouched (§3.1, D-39)."""
    path = tmp_path / "graph.json"
    assert write_graph(build_graph([load_fixture("supabase-ddl.json")]), path) is True
    before = path.read_bytes()
    assert write_graph(build_graph([load_fixture("supabase-live.json")]), path) is False
    assert path.read_bytes() == before


# --- fallback path: hand-authored 1.1 fixtures, unqualified names (D-42.7) --------


def test_fallback_fixture_resolves_to_the_same_edges():
    """`FROM orders o` (unqualified, hand-authored 1.1 artifact) must
    resolve by unique match to the same graph the qualified customer
    snapshot produces — same node and edge identities and mappings."""
    fallback = build_graph([load_fixture("supabase-ddl.json")])
    primary = customer_graph()
    assert {n["id"] for n in fallback["nodes"]} >= {n["id"] for n in primary["nodes"]}
    for edge in primary["edges"]:
        counterpart = graph_edge(fallback, edge["source"], edge["target"])
        assert counterpart["id"] == edge["id"]
        assert counterpart["operation"] == edge["operation"]
        assert counterpart["columns"] == edge["columns"]


# --- CLI (deliverable 4): snapshot(s) -> <kb>/lineage/graph.json --------------------


def test_cli_writes_graph_then_byte_noop(tmp_path, capsys):
    kb = tmp_path / "kb"
    snapshot_path = str(FIXTURES_DIR / CUSTOMER)

    assert lineage_cli([snapshot_path, "--kb", str(kb)]) == 0
    assert "written" in capsys.readouterr().out
    first = tree_bytes(kb)
    assert list(first) == ["lineage/graph.json"]  # writes nothing else (D-42.9)

    assert lineage_cli([snapshot_path, "--kb", str(kb)]) == 0
    assert "unchanged" in capsys.readouterr().out
    assert tree_bytes(kb) == first


def test_cli_parse_failure_is_loud_and_writes_nothing(tmp_path, capsys):
    snapshot = load_fixture(CUSTOMER)
    broken = next(o for o in snapshot["objects"] if o["kind"] == "view")
    broken["stats"]["definition"] = ")))) not sql (((("
    snapshot_path = tmp_path / "broken.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    kb = tmp_path / "kb"
    assert lineage_cli([str(snapshot_path), "--kb", str(kb)]) == 1
    err = capsys.readouterr().err
    assert "supabase.public.v_daily_revenue" in err  # attributable: FQN
    assert "view-def sha256:" in err                 # attributable: definition hash
    assert not (kb / "lineage" / "graph.json").exists()  # complete or absent (§3.6)


def test_cli_rejects_invalid_snapshot(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"snapshot_version": "1"}', encoding="utf-8")
    assert lineage_cli([str(bad), "--kb", str(tmp_path / "kb")]) == 1


# --- CP-7 F-4: gateway attestations (publish → report nodes/edges) -------------


def gateway_attestation(target_node="looker_studio.report.tl-abc123"):
    return {
        "source": VIEW,
        "target": target_node,
        "operation": "ingest",
        "evidence": {"tier": "pipeline-tool", "ref": "gateway:audit-1"},
        "source_meta": {"resolved": True, "kind": "view",
                        "schema": "public", "name": "v_daily_revenue"},
        "target_meta": {"resolved": True, "kind": "report",
                        "schema": None, "name": "tl-abc123"},
    }


def test_gateway_attestations_land_as_report_nodes_and_edges():
    graph = build_graph([load_fixture(CUSTOMER)],
                        gateway_attestations=[gateway_attestation()])
    node = graph_node(graph, "looker_studio.report.tl-abc123")
    assert node["node_kind"] == "report"
    assert node["resolved"] is True
    # BI-side node: resolved but doc-less (no machine doc exists for it).
    assert "doc" not in node
    edge = graph_edge(graph, VIEW, "looker_studio.report.tl-abc123")
    assert edge["operation"] == "ingest"
    assert edge["trust"] == "pipeline-tool"
    assert edge["evidence"] == [{"tier": "pipeline-tool", "ref": "gateway:audit-1"}]
    assert [i for i in graph["inputs"] if i["kind"] == "gateway"] == [
        {"kind": "gateway", "attestations": 1}
    ]


def test_gateway_attestations_are_deterministic_and_additive():
    plain = build_graph([load_fixture(CUSTOMER)])
    once = build_graph([load_fixture(CUSTOMER)], gateway_attestations=[gateway_attestation()])
    twice = build_graph([load_fixture(CUSTOMER)], gateway_attestations=[gateway_attestation()])
    assert once == twice  # FG-1 spirit: identical inputs, identical graph
    assert plain["generated_at"] == once["generated_at"]  # snapshots alone stamp time
    assert {n["id"] for n in plain["nodes"]} < {n["id"] for n in once["nodes"]}
    assert len(once["edges"]) == len(plain["edges"]) + 1


def test_gateway_attestations_via_cli(tmp_path, capsys):
    import shutil
    snap = FIXTURES_DIR / CUSTOMER
    att = tmp_path / "attestations.json"
    att.write_text(json.dumps([gateway_attestation()]), encoding="utf-8")
    kb = tmp_path / "kb"
    assert lineage_cli([str(snap), "--kb", str(kb), "--attestations", str(att)]) == 0
    graph = json.loads((kb / "lineage" / "graph.json").read_text(encoding="utf-8"))
    assert any(n["id"] == "looker_studio.report.tl-abc123" for n in graph["nodes"])
