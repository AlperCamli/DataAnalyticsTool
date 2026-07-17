"""Contamination scan — KB spec §6 steps 1–5, walk per formats §3.4.

Sync stage 7 (spec §5.7): runs over the *finalized* classifications
(post §7-note-³) and the *newly derived* graph, and produces the status
transitions and changelog inputs the drift PR carries. New implementation
(CP-3b ruling C2) living beside the graph code; it never writes files —
``generator.statuses`` applies the front-matter edits it computes.

Inputs: the KB tree at the pinned ``kb_ref`` (front-matter reads only),
finalized per-system diff documents, and ``lineage/graph.json`` as
re-derived this run (or HEAD's when re-derivation was not required).

The scan's primary input is the declared ``depends_on`` list (K-2),
extended by exactly the declaration surfaces the specs name: entity
``maps[].object`` (KB §6 step 2), the doc's own ``object`` front-matter,
and — for grouped docs (K-4 "the roster keeps contamination flagging
uniform") — the machine sibling's roster. ``external: true`` entries are
excluded (KB-B). Step 5 is the secondary best-effort net: a token grep
for backticked FQNs (KB §8 fixes the format) across all human docs,
reported as *undeclared possible references*, never auto-flagged.

Output (JSON, deterministic ordering):

    {"contaminated": [{"doc", "status_was", "contamination": {object,
        change, detail[, path]}, "reasons": [...]}],
     "stale": [{"doc", "status_was", "objects": [fqn, ...]}],
     "undeclared_references": [{"doc", "object"}],
     "breaking": {fqn: {"change", "detail"}},
     "additive_changed": [fqn, ...]}

``contamination`` is the exact front-matter value for the doc (first
reason in (object, path-length) order); ``reasons`` carries the full set
for the changelog. Exit codes: 0 ok / 1 scan failure / 2 usage.
"""

import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

from generator import frontmatter

_SUB_LABELS = {
    "column_added": "column",
    "column_removed": "column",
    "column_type_changed": "column",
    "column_nullable_tightened": "column",
    "column_nullable_loosened": "column",
    "column_default_changed": "column",
    "column_ordinal_changed": "column",
    "key_added": "key",
    "key_removed": "key",
    "key_altered": "key",
    "stat_changed": "stat",
}


class ScanError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Step 1 — finalized classifications in


def _fqn(system: str, identity: dict) -> str:
    return f"{system}.{identity['schema']}.{identity['name']}"


def _describe_sub(sub: dict) -> str:
    label = _SUB_LABELS.get(sub["change"])
    if label is None:
        return sub["change"]
    return f"{sub['change']}: {sub['detail'][label]}"


def classify(diffs: list[dict]) -> tuple[dict, dict, set]:
    """(breaking, additive_changed, grep_fqns) from finalized diffs."""
    breaking: dict[str, dict] = {}
    additive: dict[str, str] = {}
    grep: set[str] = set()
    for diff in diffs:
        if not diff.get("severity_finalized"):
            raise ScanError(
                f"diff for system {diff.get('system')!r} is not severity-finalized — "
                "the scan runs only over final classifications (sync §5.6/§5.7)"
            )
        system = diff["system"]
        for obj in diff.get("removed", []):
            fqn = _fqn(system, obj["identity"])
            breaking[fqn] = {"change": "removed", "detail": "object removed from snapshot"}
            grep.add(fqn)
        for obj in diff.get("added", []):
            grep.add(_fqn(system, obj["identity"]))
        for obj in diff.get("changed_structural", []):
            fqn = _fqn(system, obj["identity"])
            grep.add(fqn)
            subs = obj.get("sub_diffs", [])
            breaking_subs = [s for s in subs if s["severity"] == "breaking"]
            if obj.get("severity") == "breaking":
                changes = sorted({s["change"] for s in breaking_subs}) or ["changed"]
                breaking[fqn] = {
                    "change": "+".join(changes),
                    "detail": "; ".join(_describe_sub(s) for s in breaking_subs)
                    or "structural change",
                }
            else:
                additive[fqn] = "; ".join(_describe_sub(s) for s in subs)
    return breaking, additive, grep


# ---------------------------------------------------------------------------
# KB tree reads (front-matter only; never bodies except the step-5 grep)


_MACHINE_CLASSES = {"machine-object", "machine-group", "machine-index"}


def _is_machine_path(parts: tuple[str, ...]) -> bool:
    if parts[0] != "systems":
        return False
    name = parts[-1]
    return name == "index.md" or name.endswith(".schema.md")


class Doc:
    def __init__(self, rel: str, fm: dict | None, body: str):
        self.rel = rel
        self.fm = fm or {}
        self.body = body
        self.status = self.fm.get("status")
        self.deps: set[str] = set()

    @property
    def statusable(self) -> bool:
        doc_class = self.fm.get("doc_class")
        return (
            isinstance(self.status, str)
            and isinstance(doc_class, str)
            and doc_class not in _MACHINE_CLASSES
        )


def _dep_entries(value) -> list[str]:
    """Normalize a depends_on/maps list; KB-B external entries excluded."""
    out = []
    for entry in value or []:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict) and not entry.get("external"):
            obj = entry.get("object")
            if isinstance(obj, str):
                out.append(obj)
    return out


def load_docs(kb_dir: Path) -> list[Doc]:
    """Human docs (everything but machine-owned files), deps resolved."""
    machine_fm: dict[str, dict] = {}
    docs: list[Doc] = []
    for path in sorted(kb_dir.rglob("*.md")):
        rel = path.relative_to(kb_dir).as_posix()
        parts = tuple(rel.split("/"))
        if any(p.startswith(".") for p in parts):
            continue
        fm, body = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        doc_class = (fm or {}).get("doc_class")
        if doc_class in _MACHINE_CLASSES or (fm is None and _is_machine_path(parts)):
            if isinstance(fm, dict):
                machine_fm[rel] = fm
            continue
        docs.append(Doc(rel, fm, body))

    for doc in docs:
        fm = doc.fm
        doc.deps.update(_dep_entries(fm.get("depends_on")))
        doc.deps.update(_dep_entries(fm.get("maps")))
        if isinstance(fm.get("object"), str):
            doc.deps.add(fm["object"])
        # K-4 roster: the machine sibling's identity is an implicit
        # dependency — <stem>.md relies on <stem>.schema.md's object(s).
        sibling = machine_fm.get(doc.rel[:-3] + ".schema.md")
        if sibling:
            if isinstance(sibling.get("object"), str):
                doc.deps.add(sibling["object"])
            for entry in sibling.get("objects") or []:
                if isinstance(entry, dict) and isinstance(entry.get("object"), str):
                    doc.deps.add(entry["object"])
    return docs


# ---------------------------------------------------------------------------
# Step 3 — the downstream walk (formats §3.4: min-hop BFS, visit once,
# cycles never re-traversed, unbounded depth, edge-id path recorded)


def contamination_walk(graph: dict, start: str) -> dict[str, list[str]]:
    """{reached fqn: edge-id path from start}; deterministic (adjacency
    sorted by edge id, breadth-first so paths are min-hop)."""
    adjacency: dict[str, list[dict]] = {}
    for edge in sorted(graph["edges"], key=lambda e: e["id"]):
        adjacency.setdefault(edge["source"], []).append(edge)
    paths: dict[str, list[str]] = {}
    queue = deque([start])
    visited = {start}
    paths[start] = []
    while queue:
        fqn = queue.popleft()
        for edge in adjacency.get(fqn, ()):
            target = edge["target"]
            if target in visited:
                continue
            visited.add(target)
            paths[target] = paths[fqn] + [edge["id"]]
            queue.append(target)
    return paths


# ---------------------------------------------------------------------------
# Steps 2–5 assembled


def scan(kb_dir: Path, diffs: list[dict], graph: dict) -> dict:
    breaking, additive, grep_fqns = classify(diffs)
    docs = load_docs(kb_dir)
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    sibling_of = {
        n["doc"][: -len(".schema.md")] + ".md": n["id"]
        for n in graph["nodes"]
        if "doc" in n
    }

    # (doc rel, breaking fqn) -> reason; first write wins (min-hop BFS
    # emits the shortest path first; direct declarations run before walks)
    reasons: dict[tuple[str, str], dict] = {}

    def flag(doc: Doc, fqn: str, path: list[str]) -> None:
        if not doc.statusable:
            return
        key = (doc.rel, fqn)
        if key not in reasons:
            reason = {"object": fqn, **breaking[fqn]}
            if path:
                reason["path"] = path
            reasons[key] = reason

    for fqn in sorted(breaking):
        # step 2: declared dependents of the breaking object itself
        for doc in docs:
            if fqn in doc.deps:
                flag(doc, fqn, [])
        # step 3: downstream walk on the newly derived graph — visited in
        # (hops, fqn) order so the reason recorded per doc is the
        # shortest lineage route to one of its dependencies
        if fqn in nodes_by_id:
            walked = sorted(
                contamination_walk(graph, fqn).items(),
                key=lambda kv: (len(kv[1]), kv[0]),
            )
            for reached, path in walked:
                if reached == fqn:
                    continue
                for doc in docs:
                    if reached in doc.deps:
                        flag(doc, fqn, path)
                    elif doc.rel in sibling_of and sibling_of[doc.rel] == reached:
                        flag(doc, fqn, path)  # docs reachable via `doc` (§3.4)

    contaminated_docs: dict[str, list[dict]] = {}
    for (rel, _fqn_key), reason in reasons.items():
        contaminated_docs.setdefault(rel, []).append(reason)

    # step 4: additive-only changes → verified dependents go stale
    stale: list[dict] = []
    for doc in docs:
        if doc.rel in contaminated_docs or doc.status != "verified":
            continue
        hits = sorted(fqn for fqn in additive if fqn in doc.deps)
        if hits:
            stale.append({"doc": doc.rel, "status_was": doc.status, "objects": hits})

    # step 5: secondary token grep (KB §8 backticked-FQN format), hits
    # not covered by the declaration surfaces above
    undeclared: list[dict] = []
    for doc in docs:
        text = doc.body  # for docs without front-matter this is the whole file
        for fqn in sorted(grep_fqns):
            if fqn in doc.deps:
                continue  # covered by steps 2–4
            if re.search(r"`" + re.escape(fqn) + r"(?: \([a-z_]+\))?`", text):
                undeclared.append({"doc": doc.rel, "object": fqn})

    contaminated = []
    for rel in sorted(contaminated_docs):
        doc = next(d for d in docs if d.rel == rel)
        ordered = sorted(
            contaminated_docs[rel],
            key=lambda r: (len(r.get("path", [])), r["object"]),
        )
        contaminated.append(
            {
                "doc": rel,
                "status_was": doc.status,
                "contamination": ordered[0],
                "reasons": ordered,
            }
        )

    return {
        "contaminated": contaminated,
        "stale": sorted(stale, key=lambda s: s["doc"]),
        "undeclared_references": sorted(
            undeclared, key=lambda u: (u["doc"], u["object"])
        ),
        "breaking": {fqn: breaking[fqn] for fqn in sorted(breaking)},
        "additive_changed": sorted(additive),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lineage.scan",
        description="Contamination scan (KB §6, formats §3.4) over finalized diffs.",
    )
    parser.add_argument("--kb", required=True, metavar="DIR")
    parser.add_argument("--graph", required=True, metavar="FILE",
                        help="lineage/graph.json as of this run")
    parser.add_argument("--diff", required=True, action="append", metavar="FILE",
                        help="finalized diff JSON (repeat per system)")
    parser.add_argument("--out", metavar="FILE", help="write here instead of stdout")
    args = parser.parse_args(argv)

    try:
        with open(args.graph, encoding="utf-8") as f:
            graph = json.load(f)
        diffs = []
        for path in args.diff:
            with open(path, encoding="utf-8") as f:
                diffs.append(json.load(f))
        result = scan(Path(args.kb), diffs, graph)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
