"""Core SQL lineage: parser, merged graph, walk (task 1.9).

Consumes snapshots, never live databases. Owns ``lineage/graph.json``
exclusively and writes nothing else into the KB tree; the generator
never reads, writes, or links it (boundary D-36.2, reconfirmed D-42.9).

Public surface:

- ``snapshot_attestations`` — snapshot in, sql-parse edge attestations
  out (capability LP shape), one set per view/matview definition.
- ``build_graph`` — attestation sets in, merged ``graph.json`` document
  out (formats spec §3; F-1/F-2 identity and evidence merging).
- ``write_graph`` — canonical serialization with the §3.1 byte-no-op
  rule (D-39) and atomic write.
- ``get_lineage`` — the LP walk (formats §3.4, MCP §6.5 semantics);
  CP-4's MCP tool wraps this later.
"""

from lineage.graph import build_graph, edge_id, merge_attestations
from lineage.parser import LineageParseError, snapshot_attestations
from lineage.walk import get_lineage
from lineage.writer import render_graph, write_graph

__all__ = [
    "LineageParseError",
    "build_graph",
    "edge_id",
    "get_lineage",
    "merge_attestations",
    "render_graph",
    "snapshot_attestations",
    "write_graph",
]
