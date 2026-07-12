"""get_lineage walk semantics (formats §3.4, MCP §6.5, D-43): direction,
depth bounds, node-level traversal with column payload verbatim, cycle
reporting (FG-4), dangling served flagged (FG-3), absent-FQN empty result."""

import pytest

from lineage import get_lineage, merge_attestations
from lineage.graph import edge_id


def make_graph(*attestations):
    nodes, edges = merge_attestations(list(attestations))
    return {"graph_version": "1", "generated_at": "2026-07-13T00:00:00Z",
            "inputs": [], "nodes": nodes, "edges": edges}


def flow(source, target, operation="derive", columns=None, resolved=True):
    att = {
        "source": source, "target": target, "operation": operation,
        "evidence": {"tier": "pipeline-tool", "ref": f"test:{source}->{target}"},
        "target_meta": {"resolved": True, "kind": "view",
                        "schema": "public", "name": target.rsplit(".", 1)[-1]},
    }
    if resolved:
        att["source_meta"] = {"resolved": True, "kind": "table",
                              "schema": "public", "name": source.rsplit(".", 1)[-1]}
    if columns is not None:
        att["columns"] = columns
    return att


A, B, C, D, E = (f"demo.public.{n}" for n in "abcde")
CHAIN = make_graph(flow(A, B), flow(B, C), flow(C, D), flow(D, E))


def node_ids(result):
    return {n["id"] for n in result["nodes"]}


# --- direction ---------------------------------------------------------------


def test_upstream_reverses_data_flow():
    result = get_lineage(CHAIN, C, "upstream", depth=None)
    assert node_ids(result) == {A, B, C}


def test_downstream_follows_data_flow():
    result = get_lineage(CHAIN, C, "downstream", depth=None)
    assert node_ids(result) == {C, D, E}


def test_both_is_the_union_root_once():
    result = get_lineage(CHAIN, C, "both", depth=None)
    assert node_ids(result) == {A, B, C, D, E}
    assert sum(n["id"] == C for n in result["nodes"]) == 1
    assert next(n for n in result["nodes"] if n["id"] == C)["depth"] == 0


def test_invalid_direction_raises():
    with pytest.raises(ValueError, match="direction"):
        get_lineage(CHAIN, C, "sideways")


# --- depth bounds --------------------------------------------------------------


def test_default_depth_is_three():
    result = get_lineage(CHAIN, E, "upstream")
    assert node_ids(result) == {B, C, D, E}  # 3 hops, a excluded


def test_depth_one():
    result = get_lineage(CHAIN, E, "upstream", depth=1)
    assert node_ids(result) == {D, E}
    assert len(result["edges"]) == 1


def test_depth_none_is_unbounded():
    """The contamination scan's mode (§3.4); the 10-cap is CP-4's."""
    result = get_lineage(CHAIN, E, "upstream", depth=None)
    assert node_ids(result) == {A, B, C, D, E}


def test_negative_depth_raises():
    with pytest.raises(ValueError, match="depth"):
        get_lineage(CHAIN, C, "upstream", depth=-1)


def test_depths_are_min_hops():
    result = get_lineage(CHAIN, E, "upstream", depth=None)
    assert {n["id"]: n["depth"] for n in result["nodes"]} == {
        E: 0, D: 1, C: 2, B: 3, A: 4
    }
    assert [n["depth"] for n in result["nodes"]] == sorted(
        n["depth"] for n in result["nodes"]
    )


# --- payload: node-level walk, column-level data served verbatim (FM-1, D-43) ---


def test_edges_carry_columns_evidence_trust_verbatim():
    graph = make_graph(
        flow(A, B, operation="aggregate",
             columns=[{"from": ["net"], "to": "net_total"}]),
    )
    result = get_lineage(graph, B, "upstream")
    edge = result["edges"][0]
    assert edge["columns"] == [{"from": ["net"], "to": "net_total"}]
    assert edge["trust"] == "pipeline-tool"
    assert edge["evidence"][0]["tier"] == "pipeline-tool"
    assert edge["operation"] == "aggregate"


def test_dangling_node_served_flagged():
    graph = make_graph(flow("demo.ambiguous", B, resolved=False))
    result = get_lineage(graph, B, "upstream")
    dangling = next(n for n in result["nodes"] if n["id"] == "demo.ambiguous")
    assert dangling["resolved"] is False
    assert dangling["node_kind"] == "external"


# --- absent FQN: empty result, root echoed, not an error (D-43 ruling) -----------


def test_absent_fqn_returns_empty_result():
    result = get_lineage(CHAIN, "demo.public.nothing", "both", depth=None)
    assert result == {
        "root": "demo.public.nothing", "direction": "both", "depth": None,
        "nodes": [], "edges": [], "cycles": [],
    }


# --- cycles (FG-4): both walks terminate, cycle reported --------------------------


CYCLIC = make_graph(flow(A, B), flow(B, A, operation="ingest"))


def test_cycle_terminates_and_is_reported_downstream():
    result = get_lineage(CYCLIC, A, "downstream", depth=None)
    assert node_ids(result) == {A, B}
    assert result["cycles"] == [edge_id(B, A, "ingest")]


def test_cycle_terminates_and_is_reported_upstream():
    result = get_lineage(CYCLIC, A, "upstream", depth=None)
    assert node_ids(result) == {A, B}
    assert len(result["cycles"]) == 1


def test_acyclic_reports_no_cycles():
    assert get_lineage(CHAIN, C, "both", depth=None)["cycles"] == []
