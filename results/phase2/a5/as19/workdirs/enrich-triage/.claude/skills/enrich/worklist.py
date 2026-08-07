"""Deterministic contamination work list for the enrich skill (spec §6 S1c).

Walks a KB checkout and builds the triage work list: every doc whose
front-matter says `status: contaminated`, what contaminated it, what the
estate says about that object *now*, and which signals a session needs
before it can classify the doc. It decides nothing — classification is a
judgment about prose against facts, and this file has no business making
it. What it does is put both in one place, deterministically, so a
session is not re-deriving the same joins ten times.

Per doc it reports:

* **the marker** — `contamination: {object, change, detail, path}` as sync
  wrote it, including the lineage route where the contamination was
  inherited rather than direct;
* **the facts now** — for the contaminating object: its current
  `schema_hash`, its column names, and its CHECK constraints where the
  snapshot carries them (`stats.checks`, SS-5). This is the evidence the
  SS-5-confirms-prose call is made on;
* **signals** — `dependency_unresolved` (a `depends_on` FQN the snapshot
  no longer has: a repair no re-grounding can perform alone),
  `was_verified` (a certified claim now under doubt, which outranks a
  draft), `mentions` (the changed object's tokens appearing in this doc's
  text, so a doc that never speaks about what changed is visible as such),
  and `on_report_path` (a golden in `.contextlayer/benchmark/suite.yaml`
  expects this object — KB §3.1).

Ordering is severity-first and stable: unresolved dependencies, then
previously-verified docs, then report-path docs, then blast group size,
then path. `--batches` groups the same list into review batches of at
most ten (SP-3), keeping docs that share a contaminating cause together —
one story per pull request, which is what makes the diff reviewable.

Stdlib only, except that report-path ordering needs PyYAML to read the
suite; without it the tool says the ordering is unavailable rather than
pretending the KB has no goldens. Output is sorted everywhere: two runs
over one tree are byte-identical.

    python worklist.py --kb <kb-clone-root> [--json] [--batches]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:  # the KB's own vendored wheel pins it; a bare python3 may not have it
    import yaml
except ImportError:  # pragma: no cover - exercised by the no-yaml path
    yaml = None

BATCH_MAX = 10  # SP-3, unchanged

_FENCE = "---\n"
_BARE_KEY = re.compile(r"([,{]\s*)([A-Za-z_][A-Za-z0-9_]*):")
_STATUS = re.compile(r"^status:\s*(\S+)\s*$", re.MULTILINE)
_OBJECT = re.compile(r"^object:\s*(\S+)\s*$", re.MULTILINE)
_LAST_VERIFIED = re.compile(r"^last_verified:\s*(.+?)\s*$", re.MULTILINE)
_HASH = re.compile(r'^written_against_schema_hash:\s*"?([^"\s]+)"?\s*$', re.MULTILINE)
_CONTAMINATION = re.compile(r"^contamination:\s*(.+?)\s*$", re.MULTILINE)
_LIST_ITEM = re.compile(r"^  - (\S+)\s*$", re.MULTILINE)


def _split(text: str) -> tuple[str, str]:
    """(front-matter, body). Empty front-matter for a doc without one."""
    if not text.startswith(_FENCE):
        return "", text
    end = text.find("\n---\n", len(_FENCE) - 1)
    if end == -1:
        return "", text
    return text[len(_FENCE) : end + 1], text[end + len("\n---\n") :]


def _block_list(head: str, key: str) -> list[str]:
    """The `key:` block-sequence entries — `depends_on`, `sources`."""
    items: list[str] = []
    collecting = False
    for line in head.splitlines():
        if not collecting:
            collecting = line.rstrip() == f"{key}:"
            continue
        if line.startswith("  - "):
            items.append(line[4:].strip().strip('"'))
        elif line.strip():
            break  # the next key ends the block
    return items


def _block_map_keys(head: str, key: str) -> list[str]:
    """The keys of a `key:` block mapping — `column_purposes`."""
    keys: list[str] = []
    collecting = False
    for line in head.splitlines():
        if not collecting:
            collecting = line.rstrip() == f"{key}:"
            continue
        if line.startswith("  ") and ":" in line and not line.startswith("  - "):
            keys.append(line.strip().split(":", 1)[0].strip())
        elif line.strip():
            break
    return keys


def _parse_contamination(raw: str) -> dict | None:
    """Sync writes a one-line YAML flow mapping with bare keys and
    JSON-quoted strings; quoting the keys makes it JSON."""
    if raw.strip() in ("null", "~", ""):
        return None
    try:
        return json.loads(_BARE_KEY.sub(r'\1"\2":', raw))
    except json.JSONDecodeError:
        return {"unparsed": raw}


# --------------------------------------------------------------------------
# the estate's own facts


def load_snapshots(kb: Path) -> dict[str, dict]:
    """{FQN: object} over the accepted snapshots (KB §3)."""
    objects: dict[str, dict] = {}
    for path in sorted((kb / ".contextlayer" / "snapshots").glob("*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        system = snap.get("system", path.stem)
        for obj in snap.get("objects", []):
            schema = obj.get("schema") or obj.get("group") or ""
            fqn = ".".join(p for p in (system, schema, obj.get("name", "")) if p)
            objects[fqn] = obj
    return objects


def report_path_objects(kb: Path) -> tuple[set[str], str | None]:
    """Objects the golden suite expects (KB §3.1), and why not if absent."""
    suite = kb / ".contextlayer" / "benchmark" / "suite.yaml"
    if not suite.is_file():
        return set(), f"no golden suite at {suite.relative_to(kb).as_posix()}"
    if yaml is None:
        return set(), "PyYAML unavailable — report-path ordering is off"
    raw = yaml.safe_load(suite.read_text(encoding="utf-8")) or {}
    expected: set[str] = set()
    for case in raw.get("cases", []) or []:
        expected.update(case.get("expected_objects", []) or [])
    return expected, None


def object_facts(fqn: str | None, objects: dict[str, dict]) -> dict:
    """What the current snapshot says about the contaminating object."""
    obj = objects.get(fqn or "")
    if obj is None:
        return {"resolves": False}
    stats = obj.get("stats") or {}
    return {
        "resolves": True,
        "kind": obj.get("kind"),
        "schema_hash": obj.get("schema_hash"),
        "columns": sorted(c["name"] for c in obj.get("columns", []) if c.get("name")),
        "checks": list(stats.get("checks") or []),
    }


def changed_columns(facts: dict) -> list[str]:
    """The columns the contaminating change actually touches.

    For an SS-5 `stat_changed: checks` marking that is the columns the new
    CHECK constraints constrain — the only part of the object that moved.
    Without checks to read, every column is in scope and the caller is
    told as much by getting the whole list.
    """
    columns = facts.get("columns", [])
    checks = facts.get("checks") or []
    if not checks:
        return list(columns)
    blob = " ".join(checks)
    return [c for c in columns if re.search(rf"\b{re.escape(c)}\b", blob)]


def _mentions(text: str, fqn: str | None, facts: dict) -> list[str]:
    """Which of the *changed* things this doc actually talks about.

    A doc that never names the changed object, and says nothing about the
    columns the change constrains, is a different repair from one whose
    prose decodes the very enum that just gained a CHECK — and the
    difference is visible here rather than after reading thirty files.

    Searched over the doc's *claims* — body text plus the purpose keys —
    never over its mechanical front-matter: `contamination:` and
    `depends_on:` both name the changed object by construction, so
    including them would report every doc as speaking about everything.
    """
    hits: list[str] = []
    lowered = text.lower()
    if fqn:
        for token in (fqn, fqn.split(".")[-1]):
            if token.lower() in lowered:
                hits.append(token)
    for column in changed_columns(facts):
        if re.search(rf"\b{re.escape(column)}\b", text):
            hits.append(column)
    return sorted(set(hits))


# --------------------------------------------------------------------------


def worklist(kb: Path) -> dict:
    objects = load_snapshots(kb)
    expected, expected_note = report_path_objects(kb)

    docs: list[dict] = []
    for path in sorted(kb.rglob("*.md")):
        rel = path.relative_to(kb).as_posix()
        if rel.startswith(".git/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        head, body = _split(text)
        status_m = _STATUS.search(head)
        if not status_m or status_m.group(1) != "contaminated":
            continue

        cont_m = _CONTAMINATION.search(head)
        contamination = _parse_contamination(cont_m.group(1)) if cont_m else None
        cause = (contamination or {}).get("object")
        facts = object_facts(cause, objects)
        depends_on = _block_list(head, "depends_on")
        last_verified = (_LAST_VERIFIED.search(head).group(1)
                         if _LAST_VERIFIED.search(head) else "null")
        own_object = _OBJECT.search(head).group(1) if _OBJECT.search(head) else None
        written_against = _HASH.search(head).group(1) if _HASH.search(head) else None

        touches = sorted({own_object} | set(depends_on)) if own_object else sorted(depends_on)
        docs.append({
            "doc": rel,
            "object": own_object,
            "contamination": contamination,
            "cause": cause,
            "cause_facts": facts,
            "depends_on": depends_on,
            "dependency_unresolved": [f for f in depends_on if f not in objects],
            "was_verified": last_verified not in ("null", "~", ""),
            "written_against_schema_hash": written_against,
            "own_hash_current": (
                None if not own_object or own_object not in objects
                else objects[own_object].get("schema_hash") == written_against),
            "changed_columns": changed_columns(facts),
            "mentions": _mentions(
                body + "\n" + "\n".join(_block_map_keys(head, "column_purposes")),
                cause, facts),
            "on_report_path": bool(set(touches) & expected),
            "body_words": len(body.split()),
        })

    blast: dict[str, int] = {}
    for entry in docs:
        if entry["cause"]:
            blast[entry["cause"]] = blast.get(entry["cause"], 0) + 1
    for entry in docs:
        entry["blast_group"] = blast.get(entry["cause"] or "", 0)

    docs.sort(key=lambda d: (
        not d["dependency_unresolved"],   # unresolved refs first
        not d["was_verified"],            # then certified claims under doubt
        not d["on_report_path"],          # then what a golden depends on
        -d["blast_group"],                # then the big shared causes
        d["doc"],
    ))
    return {
        "kb": str(kb),
        "contaminated": len(docs),
        "report_path_note": expected_note,
        "docs": docs,
        "blast": [{"object": o, "count": c} for o, c in
                  sorted(blast.items(), key=lambda kv: (-kv[1], kv[0]))],
    }


def batches(docs: list[dict], size: int = BATCH_MAX) -> list[list[dict]]:
    """Review batches of at most `size`, docs sharing a cause kept together.

    A batch is a pull request somebody reads end to end, so it should tell
    one story: these docs, this change, this repair. A group larger than a
    batch is split (it keeps its story, in parts); small groups are packed
    together in worklist order and never split needlessly — the severity
    ordering means what shares a batch already shares a reason to be read.
    """
    by_cause: dict[str, list[dict]] = {}
    for doc in docs:
        by_cause.setdefault(doc["cause"] or "(unmarked)", []).append(doc)
    groups = sorted(by_cause.values(), key=lambda g: docs.index(g[0]))

    out: list[list[dict]] = []
    current: list[dict] = []
    for group in groups:
        for i in range(0, len(group), size):
            chunk = group[i : i + size]
            if len(current) + len(chunk) > size:
                if current:
                    out.append(current)
                current = []
            current.extend(chunk)
    if current:
        out.append(current)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="enrich contamination work list (S1c)")
    ap.add_argument("--kb", type=Path, required=True, help="KB checkout root")
    ap.add_argument("--json", action="store_true", help="machine output")
    ap.add_argument("--batches", action="store_true", help="propose review batches (≤10)")
    args = ap.parse_args(argv)
    if not args.kb.is_dir():
        print(f"error: {args.kb} is not a directory", file=sys.stderr)
        return 2

    result = worklist(args.kb)
    if args.batches:
        result["batches"] = [[d["doc"] for d in b] for b in batches(result["docs"])]
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"contaminated: {result['contaminated']} doc(s) in {args.kb}")
    if result["report_path_note"]:
        print(f"note: {result['report_path_note']}")
    for entry in result["docs"]:
        cont = entry["contamination"] or {}
        route = f" via {cont.get('path')}" if cont.get("path") else ""
        flags = [f for f, on in (
            ("REPORT-PATH", entry["on_report_path"]),
            ("WAS-VERIFIED", entry["was_verified"]),
            ("UNRESOLVED-DEP", bool(entry["dependency_unresolved"])),
        ) if on]
        print(f"\n{entry['doc']}  [{' '.join(flags) or 'draft-tier'}]")
        print(f"  ← {entry['cause'] or '(no marker)'} "
              f"({cont.get('change', '?')}: {cont.get('detail', '?')}){route}")
        if entry["dependency_unresolved"]:
            print(f"  depends_on does not resolve: {', '.join(entry['dependency_unresolved'])}")
        if entry["cause_facts"].get("checks"):
            for check in entry["cause_facts"]["checks"]:
                print(f"  now: {check}")
        print(f"  doc mentions: {', '.join(entry['mentions']) or '(nothing of the changed object)'}")
    if args.batches:
        print()
        for i, batch in enumerate(batches(result["docs"]), 1):
            print(f"batch {i} ({len(batch)}): {', '.join(d['doc'] for d in batch)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
