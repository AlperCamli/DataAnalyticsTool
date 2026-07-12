"""Graph assembly: F-1 identity, F-2 evidence merging, D-39 envelope and
serialization, the §3.1 byte-no-op write rule (FG-1)."""

import copy
import hashlib
import json

import pytest

from lineage import build_graph, edge_id, merge_attestations, render_graph, write_graph
from lineage.graph import snapshot_body_hash
from tests.conftest import graph_edge, sql_object, sql_snapshot


def attestation(source, target, operation, tier, ref, columns=None):
    att = {
        "source": source, "target": target, "operation": operation,
        "evidence": {"tier": tier, "ref": ref},
        "source_meta": {"resolved": True, "kind": "table",
                        "schema": "public", "name": source.rsplit(".", 1)[-1]},
        "target_meta": {"resolved": True, "kind": "view",
                        "schema": "public", "name": target.rsplit(".", 1)[-1]},
    }
    if columns is not None:
        att["columns"] = columns
    return att


# --- edge identity (F-1, D-40) -------------------------------------------------


def test_edge_id_byte_encoding_is_frozen():
    expected = "sha256:" + hashlib.sha256(
        "demo.public.a\ndemo.public.v\njoin".encode("utf-8")
    ).hexdigest()
    assert edge_id("demo.public.a", "demo.public.v", "join") == expected


def test_edge_id_stable_when_only_column_mappings_change():
    """FG-1 second clause: refining a mapping never mints a new edge."""
    base = [
        sql_object("table", "public", "t", ["a", "b"]),
        sql_object("view", "public", "v", ["x"],
                   definition="SELECT a AS x FROM public.t"),
    ]
    refined = copy.deepcopy(base)
    refined[1]["stats"]["definition"] = "SELECT b AS x FROM public.t"

    g1 = build_graph([sql_snapshot(*base)])
    g2 = build_graph([sql_snapshot(*refined)])
    e1 = graph_edge(g1, "demo.public.t", "demo.public.v")
    e2 = graph_edge(g2, "demo.public.t", "demo.public.v")
    assert e1["id"] == e2["id"]
    assert e1["columns"] != e2["columns"]


# --- evidence merging (F-2, FG-2) ------------------------------------------------


def test_two_tiers_merge_into_one_edge_trust_strongest():
    nodes, edges = merge_attestations([
        attestation("demo.public.t", "demo.public.v", "aggregate",
                    "sql-parse", "view-def sha256:aa",
                    columns=[{"from": ["net"], "to": "net_total"}]),
        attestation("demo.public.t", "demo.public.v", "aggregate",
                    "pipeline-tool", "dbt:model.sales.v"),
    ])
    assert len(edges) == 1
    edge = edges[0]
    assert edge["evidence"] == [
        {"tier": "pipeline-tool", "ref": "dbt:model.sales.v"},
        {"tier": "sql-parse", "ref": "view-def sha256:aa"},
    ]
    assert edge["trust"] == "pipeline-tool"
    assert edge["columns"] == [{"from": ["net"], "to": "net_total"}]


def test_same_pair_different_operation_is_a_different_edge():
    _, edges = merge_attestations([
        attestation("demo.public.t", "demo.public.v", "aggregate", "sql-parse", "r1"),
        attestation("demo.public.t", "demo.public.v", "filter", "sql-parse", "r2"),
    ])
    assert len(edges) == 2
    assert len({e["id"] for e in edges}) == 2


def test_unknown_operation_rejected_at_delivery():
    with pytest.raises(ValueError, match="LP-1 taxonomy"):
        merge_attestations([
            attestation("demo.public.t", "demo.public.v", "transmogrify",
                        "sql-parse", "r"),
        ])


def test_unknown_tier_rejected():
    with pytest.raises(ValueError, match="LP-2"):
        merge_attestations([
            attestation("demo.public.t", "demo.public.v", "join", "vibes", "r"),
        ])


# --- envelope (D-39) ---------------------------------------------------------------


def snapshot_with_view(**kwargs):
    return sql_snapshot(
        sql_object("table", "public", "t", ["a"]),
        sql_object("view", "public", "v", ["a"],
                   definition="SELECT a FROM public.t"),
        **kwargs,
    )


def test_envelope_inputs_pin_canonical_body_hash():
    snapshot = snapshot_with_view()
    graph = build_graph([snapshot])
    assert graph["graph_version"] == "1"
    assert graph["inputs"] == [
        {"kind": "sql-parse", "snapshot_ref": {"demo": snapshot_body_hash(snapshot)}}
    ]
    assert graph["generated_at"] == snapshot["captured_at"]


def test_multi_system_inputs_one_sorted_map():
    s1 = snapshot_with_view(system="zeta", captured_at="2026-07-10T00:00:00Z")
    s2 = snapshot_with_view(system="alpha", captured_at="2026-07-12T00:00:00Z")
    graph = build_graph([s1, s2])
    assert list(graph["inputs"][0]["snapshot_ref"]) == ["alpha", "zeta"]
    assert graph["generated_at"] == "2026-07-12T00:00:00Z"  # latest captured_at


def test_duplicate_system_rejected():
    with pytest.raises(ValueError, match="duplicate system"):
        build_graph([snapshot_with_view(), snapshot_with_view()])


def test_nodes_and_edges_sorted_by_id():
    graph = build_graph([sql_snapshot(
        sql_object("table", "public", "t", ["a"]),
        sql_object("table", "public", "u", ["b"]),
        sql_object("view", "public", "v", ["a", "b"],
                   definition="SELECT t.a, u.b FROM public.t t"
                              " JOIN public.u u ON t.a = u.b"),
    )])
    assert [n["id"] for n in graph["nodes"]] == sorted(n["id"] for n in graph["nodes"])
    assert [e["id"] for e in graph["edges"]] == sorted(e["id"] for e in graph["edges"])


# --- serialization and the byte-no-op rule (§3.1, FG-1) ------------------------------


def test_render_is_deterministic():
    snapshot = snapshot_with_view()
    assert render_graph(build_graph([snapshot])) == render_graph(build_graph([snapshot]))


def test_regeneration_on_unchanged_body_is_a_byte_noop(tmp_path):
    """D-33 ported: a re-snapshot with a new captured_at but an unchanged
    canonical body must leave the file byte-untouched."""
    path = tmp_path / "graph.json"
    snapshot = snapshot_with_view(captured_at="2026-07-11T00:00:00Z")
    assert write_graph(build_graph([snapshot]), path) is True
    before = path.read_bytes()

    resnap = snapshot_with_view(captured_at="2026-07-13T09:00:00Z")
    assert write_graph(build_graph([resnap]), path) is False
    assert path.read_bytes() == before
    assert json.loads(before)["generated_at"] == "2026-07-11T00:00:00Z"


def test_content_change_restamps_generated_at(tmp_path):
    path = tmp_path / "graph.json"
    write_graph(build_graph([snapshot_with_view(captured_at="2026-07-11T00:00:00Z")]), path)

    changed = sql_snapshot(
        sql_object("table", "public", "t", ["a", "b"]),
        sql_object("view", "public", "v", ["a", "b"],
                   definition="SELECT a, b FROM public.t"),
        captured_at="2026-07-13T09:00:00Z",
    )
    assert write_graph(build_graph([changed]), path) is True
    assert json.loads(path.read_text())["generated_at"] == "2026-07-13T09:00:00Z"
