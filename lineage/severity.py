"""Severity finalization (snapshot spec §7 note ³) — sync stage 6.

The diff engine holds view/matview ``definition`` changes at provisional
breaking with ``downgradable: true`` (D-3): the downgrade needs lineage.
This module applies the note-³ rule against the re-derived graph: a
``definition`` change whose re-derived output column set and mappings
are unchanged downgrades to additive-with-note. Only after this pass is
the breaking set final (sync spec §5.6).

"Output column set and mappings unchanged" is implemented as the
conjunction of:

- no column-set-shaping sub-diffs on the object (``column_added``,
  ``column_removed``, ``column_type_changed``, ``column_ordinal_changed``
  — the snapshot's own column list is authoritative for a view's output
  columns; nullable/default sub-diffs carry their own severities and do
  not block the definition downgrade), and
- the incoming edges of the object — identity (F-1: source, target,
  operation) and column mappings — are equal between the old and the
  re-derived graph. Evidence refs are excluded from the comparison by
  design: they embed the definition hash (``view-def sha256:…``) and
  always differ across a definition edit; the note asks about *mappings*.

CLI (invoked by the TypeScript orchestrator, ruling C2):

    python -m lineage.severity DIFF.json [--old-graph G.json
        --new-graph G.json] [--out FILE]

DIFF.json is ``snapshot.diff`` CLI output for one system. Graphs are
required iff the diff carries downgradable sub-diffs (a definition
change forces lineage re-derivation per sync §5.5, so the graphs exist
exactly when they are needed). Output is the same diff document with
severities finalized and ``severity_finalized: true`` stamped.

Exit codes: 0 ok / 2 usage or inconsistent inputs.
"""

import argparse
import json
import sys
from pathlib import Path

# Sub-diff kinds that change the output column set/shape (see module
# docstring); their presence forecloses the note-³ downgrade.
_COLUMN_SHAPING = frozenset(
    {"column_added", "column_removed", "column_type_changed", "column_ordinal_changed"}
)

_SEVERITY_RANK = {"additive": 1, "additive-with-note": 2, "breaking": 3}


class FinalizeError(ValueError):
    pass


def _incoming(graph: dict, fqn: str) -> dict[str, tuple]:
    """Comparable incoming-edge map: edge id -> normalized column mappings.

    Edge id is F-1 identity (source‖target‖operation), so key equality is
    identity equality; the value normalizes ``columns`` to a sorted
    tuple of (to, sorted from) pairs, absent mappings to ().
    """
    result: dict[str, tuple] = {}
    for edge in graph["edges"]:
        if edge["target"] != fqn:
            continue
        columns = tuple(
            sorted(
                (m["to"], tuple(sorted(m["from"])))
                for m in edge.get("columns", ())
            )
        )
        result[edge["id"]] = columns
    return result


def finalize_severity(
    diff: dict, old_graph: dict | None, new_graph: dict | None
) -> dict:
    """Return the diff with §7 note ³ applied; raises FinalizeError when a
    downgradable sub-diff exists but a graph side is missing."""
    system = diff["system"]
    out = json.loads(json.dumps(diff))  # deep copy; output stays plain JSON
    for obj in out.get("changed_structural", []):
        sub_diffs = obj.get("sub_diffs", [])
        downgradable = [s for s in sub_diffs if s.get("downgradable")]
        if not downgradable:
            continue
        if old_graph is None or new_graph is None:
            identity = obj["identity"]
            raise FinalizeError(
                f"diff for {system}.{identity['schema']}.{identity['name']} carries a "
                "downgradable definition change but --old-graph/--new-graph were not "
                "both supplied (sync §5.5 makes re-derivation required here)"
            )
        identity = obj["identity"]
        fqn = f"{system}.{identity['schema']}.{identity['name']}"
        shape_changed = any(s["change"] in _COLUMN_SHAPING for s in sub_diffs)
        mappings_equal = _incoming(old_graph, fqn) == _incoming(new_graph, fqn)
        for sub in downgradable:
            del sub["downgradable"]
            if not shape_changed and mappings_equal:
                sub["severity"] = "additive-with-note"
                sub["downgraded"] = "snapshot-§7-note-3"
        obj["severity"] = max(
            (s["severity"] for s in sub_diffs), key=_SEVERITY_RANK.__getitem__
        )
    out["severity_finalized"] = True
    return out


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lineage.severity",
        description="Finalize diff severities per snapshot §7 note ³ (sync §5.6).",
    )
    parser.add_argument("diff", metavar="DIFF")
    parser.add_argument("--old-graph", metavar="FILE")
    parser.add_argument("--new-graph", metavar="FILE")
    parser.add_argument("--out", metavar="FILE", help="write here instead of stdout")
    args = parser.parse_args(argv)
    if (args.old_graph is None) != (args.new_graph is None):
        print("error: --old-graph and --new-graph must be given together",
              file=sys.stderr)
        return 2
    try:
        finalized = finalize_severity(
            _load(args.diff),
            _load(args.old_graph) if args.old_graph else None,
            _load(args.new_graph) if args.new_graph else None,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(finalized, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
