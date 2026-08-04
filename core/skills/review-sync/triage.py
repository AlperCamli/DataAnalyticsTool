"""Deterministic KB triage for the review-sync skill (skill spec §7 S1).

Walks a KB checkout, reads every doc's front-matter `status:` (and its
one-line `contamination:` flow mapping, the shape `generator.statuses`
writes), and prints the inventory the impact ranking builds on: docs by
status, contamination fields parsed, and per-object blast counts.

Stdlib only — this file ships inside the skill bundle to the steward's
machine, where nothing beyond Python may be assumed. Output is sorted
everywhere: two runs over one tree are byte-identical.

    python triage.py --kb <kb-clone-root> [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_FENCE = "---\n"
_STATUS = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)
_CONTAMINATION = re.compile(r"^contamination:\s*(.+?)\s*$", re.MULTILINE)
_BARE_KEY = re.compile(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]*):")


def _front_matter(text: str) -> str | None:
    if not text.startswith(_FENCE):
        return None
    end = text.find("\n---\n", len(_FENCE) - 1)
    return None if end == -1 else text[len(_FENCE) : end + 1]


def _parse_contamination(raw: str) -> dict | None:
    """The generator writes a one-line YAML flow mapping with bare keys
    and JSON-quoted strings — quoting the keys makes it JSON."""
    if raw == "null":
        return None
    try:
        return json.loads(_BARE_KEY.sub(r'\1"\2":', raw))
    except json.JSONDecodeError:
        return {"unparsed": raw}


def triage(kb: Path) -> dict:
    counts: dict[str, int] = {}
    contaminated: list[dict] = []
    stale: list[str] = []
    for path in sorted(kb.rglob("*.md")):
        rel = path.relative_to(kb).as_posix()
        if rel.startswith(".git/"):
            continue
        head = _front_matter(path.read_text(encoding="utf-8"))
        if head is None:
            continue
        status_m = _STATUS.search(head)
        if not status_m:
            continue
        status = status_m.group(1)
        counts[status] = counts.get(status, 0) + 1
        if status == "contaminated":
            cont_m = _CONTAMINATION.search(head)
            entry: dict = {"doc": rel}
            if cont_m:
                entry["contamination"] = _parse_contamination(cont_m.group(1))
            contaminated.append(entry)
        elif status == "stale":
            stale.append(rel)

    by_object: dict[str, list[str]] = {}
    for entry in contaminated:
        obj = (entry.get("contamination") or {}).get("object")
        if isinstance(obj, str):
            by_object.setdefault(obj, []).append(entry["doc"])
    blast = [
        {"object": obj, "docs": sorted(docs), "count": len(docs)}
        for obj, docs in by_object.items()
    ]
    blast.sort(key=lambda b: (-b["count"], b["object"]))

    return {
        "counts": dict(sorted(counts.items())),
        "contaminated": contaminated,  # rglob-sorted by doc path
        "stale": stale,
        "blast": blast,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="review-sync KB triage")
    ap.add_argument("--kb", type=Path, required=True, help="KB checkout root")
    ap.add_argument("--json", action="store_true", help="machine output")
    args = ap.parse_args(argv)
    if not args.kb.is_dir():
        print(f"error: {args.kb} is not a directory", file=sys.stderr)
        return 2

    result = triage(args.kb)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print("status counts:", ", ".join(f"{k}={v}" for k, v in result["counts"].items()) or "(none)")
    for entry in result["contaminated"]:
        cont = entry.get("contamination") or {}
        route = f" via {cont.get('path')}" if cont.get("path") else ""
        print(f"contaminated  {entry['doc']}  ← {cont.get('object', '?')} ({cont.get('change', '?')}){route}")
    for doc in result["stale"]:
        print(f"stale         {doc}")
    for b in result["blast"]:
        print(f"blast {b['count']:>3}  {b['object']}  → {', '.join(b['docs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
