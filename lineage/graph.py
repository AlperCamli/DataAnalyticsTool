"""Merged lineage graph assembly (formats spec §3).

``merge_attestations`` is the merge entry point, shaped for every future
producer (provider edge sets per LP-1..3, human ``declared_edges``
blocks) but only the sql-parse producer is wired in this task (D-42.10);
``build_graph`` runs the parser over snapshots and merges.
"""

import hashlib

from snapshot.canonical import canonical_body_bytes

from generator.naming import mangle
from lineage.parser import snapshot_attestations

# LP-1 fixed taxonomy: unknown operations are rejected at delivery.
OPERATIONS = frozenset(
    {"ingest", "join", "filter", "aggregate", "derive", "cast",
     "rename", "dedupe", "business-rule"}
)

# HLR §8 P3 tier strength, strongest first (F-2/F-3: gateway rides
# pipeline-tool). LP-2 closes the set.
TIER_ORDER = ("pipeline-tool", "sql-parse", "human")


def edge_id(source: str, target: str, operation: str) -> str:
    """F-1 edge identity, byte encoding per formats §3.3 (D-40): frozen."""
    payload = f"{source}\n{target}\n{operation}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def snapshot_body_hash(snapshot: dict) -> str:
    """The canonical-body hash `inputs.snapshot_ref` pins (D-39, S-3)."""
    return "sha256:" + hashlib.sha256(canonical_body_bytes(snapshot)).hexdigest()


def merge_attestations(attestations: list[dict]) -> tuple[list[dict], list[dict]]:
    """Merge edge attestations into (nodes, edges) per F-1/F-2.

    One attestation = one `(source, target, operation)` claim with a
    single `evidence` entry (the LP result shape) plus optional
    `columns` and optional `source_meta`/`target_meta` resolution facts.
    Attestations of one identity merge into one edge with an evidence
    array; effective `trust` = strongest tier present. Column mappings
    are unioned per target column (refining a mapping must never mint a
    new edge — F-1). Nodes are exactly the edge endpoints (D-42.8).
    """
    edges: dict[str, dict] = {}
    node_meta: dict[str, dict] = {}
    for att in attestations:
        operation = att["operation"]
        if operation not in OPERATIONS:
            raise ValueError(
                f"operation {operation!r} is not in the LP-1 taxonomy "
                f"(edge {att['source']} -> {att['target']})"
            )
        tier = att["evidence"]["tier"]
        if tier not in TIER_ORDER:
            raise ValueError(f"evidence tier {tier!r} is not in the LP-2 set")
        eid = edge_id(att["source"], att["target"], operation)
        edge = edges.setdefault(
            eid,
            {"id": eid, "source": att["source"], "target": att["target"],
             "operation": operation, "_evidence": [], "_columns": {}},
        )
        edge["_evidence"].append(dict(att["evidence"]))
        for mapping in att.get("columns", ()):
            frm = edge["_columns"].setdefault(mapping["to"], set())
            frm.update(mapping["from"])
        for endpoint, meta_key in (("source", "source_meta"), ("target", "target_meta")):
            meta = att.get(meta_key)
            fqn = att[endpoint]
            known = node_meta.setdefault(fqn, {"resolved": False, "kind": "external",
                                               "schema": None, "name": None})
            if meta and meta.get("resolved") and not known["resolved"]:
                known.update(meta)

    nodes = [_node(fqn, meta) for fqn, meta in sorted(node_meta.items())]
    merged = []
    for eid in sorted(edges):
        edge = edges.pop(eid)
        evidence = sorted(
            {(e["tier"], e["ref"]) for e in edge.pop("_evidence")},
            key=lambda e: (TIER_ORDER.index(e[0]), e[1]),
        )
        columns = edge.pop("_columns")
        out = {
            "id": edge["id"], "source": edge["source"], "target": edge["target"],
            "operation": edge["operation"],
            "evidence": [{"tier": t, "ref": r} for t, r in evidence],
            "trust": evidence[0][0],
        }
        if columns:
            out["columns"] = [
                {"from": sorted(frm), "to": to} for to, frm in sorted(columns.items())
            ]
        merged.append(out)
    return nodes, merged


def _node(fqn: str, meta: dict) -> dict:
    node = {"id": fqn, "node_kind": meta["kind"], "resolved": meta["resolved"]}
    if meta["resolved"]:
        # KB machine-doc path, computed from the snapshot + naming rules
        # (single-sourced from generator.naming) — never by reading the
        # KB tree (D-42.9). The generator guarantees the doc exists for
        # every SQL object in the snapshot.
        system = fqn.split(".", 1)[0]
        node["doc"] = (
            f"systems/{mangle(system)}/{mangle(meta['schema'])}/"
            f"{mangle(meta['name'])}.schema.md"
        )
    return node


def build_graph(snapshots: list[dict]) -> dict:
    """Snapshots in, `lineage/graph.json` document out (sql-parse only).

    `generated_at` is stamped with the latest `captured_at` among the
    inputs; the writer's byte-no-op rule (D-39) decides whether that
    stamp ever reaches the file.
    """
    systems = [s["system"] for s in snapshots]
    if len(set(systems)) != len(systems):
        raise ValueError(f"duplicate system among input snapshots: {sorted(systems)}")
    attestations: list[dict] = []
    snapshot_ref: dict[str, str] = {}
    for snapshot in sorted(snapshots, key=lambda s: s["system"]):
        snapshot_ref[snapshot["system"]] = snapshot_body_hash(snapshot)
        attestations.extend(snapshot_attestations(snapshot))
    nodes, edges = merge_attestations(attestations)
    return {
        "graph_version": "1",
        "generated_at": max(s["captured_at"] for s in snapshots),
        "inputs": [{"kind": "sql-parse", "snapshot_ref": snapshot_ref}],
        "nodes": nodes,
        "edges": edges,
    }
