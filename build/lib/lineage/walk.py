"""`get_lineage` — the LP walk (formats §3.4, MCP §6.5 semantics).

Library function; CP-4's MCP tool wraps it (D-43). Node-level traversal
(FM-1 default) with column-level payload served verbatim: visitation
ignores `columns`, but every returned edge carries its full mappings,
evidence, and trust untouched — the walk never papers over column data.

Depth is edge-hops from the start node, default 3 (MCP §6.5 signature);
`depth=None` is unbounded, for the KB §6 contamination scan (§3.4 makes
it unbounded by design). The interactive 10-cap is CP-4's policy, not
enforced here.

A walk from an FQN absent from the graph returns an empty result with
the root echoed — not an error: "no lineage recorded" is a legitimate
answer (a base table no view reads).
"""

from collections import deque

DIRECTIONS = ("upstream", "downstream", "both")


def get_lineage(
    graph: dict,
    object_fqn: str,
    direction: str = "upstream",
    depth: int | None = 3,
) -> dict:
    """Walk `lineage/graph.json` from an FQN.

    Returns ``{root, direction, depth, nodes, edges, cycles}``:

    - ``nodes``: graph node objects + ``depth`` (min hops from root;
      dangling nodes ride flagged, ``resolved: false``), sorted by
      (depth, id);
    - ``edges``: traversed edge objects verbatim, sorted by id;
    - ``cycles``: edge ids that close a cycle inside the returned
      subgraph — reported, never re-traversed (FG-4).
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    if depth is not None and depth < 0:
        raise ValueError(f"depth must be >= 0 or None, got {depth!r}")

    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    result = {
        "root": object_fqn,
        "direction": direction,
        "depth": depth,
        "nodes": [],
        "edges": [],
        "cycles": [],
    }
    if object_fqn not in nodes_by_id:
        return result  # no lineage recorded — legitimate, not an error (D-43)

    downstream: dict[str, list[dict]] = {}
    upstream: dict[str, list[dict]] = {}
    for edge in graph["edges"]:
        downstream.setdefault(edge["source"], []).append(edge)
        upstream.setdefault(edge["target"], []).append(edge)

    depths: dict[str, int] = {}
    edges: dict[str, dict] = {}
    walks = ("upstream", "downstream") if direction == "both" else (direction,)
    for walk in walks:
        adjacency = upstream if walk == "upstream" else downstream
        _bfs(object_fqn, adjacency, walk, depth, depths, edges)

    result["nodes"] = [
        {**nodes_by_id[fqn], "depth": d}
        for fqn, d in sorted(depths.items(), key=lambda kv: (kv[1], kv[0]))
    ]
    result["edges"] = [edges[eid] for eid in sorted(edges)]
    result["cycles"] = _cycles(depths.keys(), edges.values())
    return result


def _bfs(
    root: str,
    adjacency: dict[str, list[dict]],
    walk: str,
    depth: int | None,
    depths: dict[str, int],
    edges: dict[str, dict],
) -> None:
    """Visit each node once per walk; record min depth and edges taken."""
    visited = {root}
    depths[root] = min(depths.get(root, 0), 0)
    queue = deque([(root, 0)])
    while queue:
        fqn, d = queue.popleft()
        if depth is not None and d >= depth:
            continue
        for edge in adjacency.get(fqn, ()):
            neighbor = edge["source"] if walk == "upstream" else edge["target"]
            edges[edge["id"]] = edge
            if neighbor in visited:
                continue
            visited.add(neighbor)
            depths[neighbor] = min(depths.get(neighbor, d + 1), d + 1)
            queue.append((neighbor, d + 1))


def _cycles(node_ids, edges) -> list[str]:
    """Edge ids closing a cycle in the returned subgraph (data-flow
    direction), found by iterative DFS; deterministic order."""
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in sorted(edges, key=lambda e: e["id"]):
        if edge["source"] in node_ids and edge["target"] in node_ids:
            adjacency.setdefault(edge["source"], []).append(
                (edge["target"], edge["id"])
            )
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in node_ids}
    closing: list[str] = []
    for start in sorted(node_ids):
        if color[start] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        color[start] = GRAY
        while stack:
            node, i = stack[-1]
            neighbors = adjacency.get(node, [])
            if i < len(neighbors):
                stack[-1] = (node, i + 1)
                target, eid = neighbors[i]
                if color[target] == GRAY:
                    closing.append(eid)  # back-edge: closes a cycle
                elif color[target] == WHITE:
                    color[target] = GRAY
                    stack.append((target, 0))
            else:
                color[node] = BLACK
                stack.pop()
    return sorted(closing)
