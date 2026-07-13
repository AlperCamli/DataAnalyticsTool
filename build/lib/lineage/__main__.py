"""Lineage CLI: snapshot(s) -> <kb-root>/lineage/graph.json.

Task 1.6 runs this alongside the render CLI against the customer repo.
Writes exactly one file — ``lineage/graph.json`` under the KB root
(exclusive ownership, D-42.9) — atomically, with the §3.1 byte-no-op
rule: regeneration on an unchanged snapshot leaves the file untouched.

Exit codes: 0 ok / 1 failed (parse failure per formats §3.6: loud,
attributable, nothing written) / 2 usage.
"""

import argparse
import json
import sys
from pathlib import Path

from snapshot.validate import validate_snapshot

from lineage.graph import build_graph
from lineage.parser import LineageParseError
from lineage.writer import write_graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lineage",
        description="Derive lineage/graph.json from snapshot(s).",
    )
    parser.add_argument("snapshots", nargs="+", metavar="SNAPSHOT",
                        help="snapshot JSON file(s), one per system")
    parser.add_argument("--kb", required=True, metavar="DIR",
                        help="KB root; writes DIR/lineage/graph.json")
    args = parser.parse_args(argv)

    docs = []
    for path in args.snapshots:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError) as e:
            print(f"error: cannot read snapshot {path}: {e}", file=sys.stderr)
            return 1
        errors, _warnings = validate_snapshot(doc)
        if errors:
            for message in errors:
                print(f"error: {path}: {message}", file=sys.stderr)
            return 1
        docs.append(doc)

    try:
        graph = build_graph(docs)
    except (LineageParseError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out = Path(args.kb) / "lineage" / "graph.json"
    changed = write_graph(graph, out)
    state = "written" if changed else "unchanged (byte-identical, §3.1)"
    print(
        f"{out}: {state} — nodes={len(graph['nodes'])} edges={len(graph['edges'])} "
        f"systems={sorted(k for i in graph['inputs'] for k in i['snapshot_ref'])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
