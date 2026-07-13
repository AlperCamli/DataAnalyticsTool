"""KB validation library: front-matter schemas + layout conformance.

Importable (task 1.6 wires it into KB CI as the KB-1 front-matter check
and the layout half of the §3 rules); ``python -m generator.validate``
is a thin CLI over it.

Scope (deliverable 4 + task 1.6): front-matter schema validation for the
§4 classes present in a generated tree, layout conformance under
``systems/``, the ``faults/`` prohibition, relative link/anchor
resolution (KB-5, §8 — external URLs are out of scope), and — when
snapshots are supplied — machine-doc set and provenance cross-checks
(missing/orphan machine docs, front-matter hash/provenance drift).
`depends_on` resolution (KB-2) needs the latest snapshot server-side and
stays with the sync engine (CP-3); entity/metric/lineage-note schemas
land with tasks 1.7/1.8.
"""

import argparse
import json
import posixpath
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from jsonschema import Draft202012Validator

from generator import frontmatter
from generator.naming import KIND_GROUPS, mangle
from generator.render import expected_docs
from generator.schemas import DOC_CLASS_SCHEMAS
from snapshot.validate import validate_snapshot

# §4.6: K-7 bootstrap artifacts carry no front-matter and are KB-1-exempt.
_ROOT_EXEMPT = frozenset({"index.md", "conventions.md"})
_GROUP_STEMS = frozenset(KIND_GROUPS.values())


@dataclass(frozen=True)
class Finding:
    path: str  # repo-relative posix path
    check: str  # "KB-1" | "KB-5" | "layout" | "provenance"
    message: str


def _validate_front_matter(rel: str, fm: dict | None) -> list[Finding]:
    if fm is None:
        return [Finding(rel, "KB-1", "no parseable front-matter block at byte 0")]
    doc_class = fm.get("doc_class")
    schema = DOC_CLASS_SCHEMAS.get(doc_class) if isinstance(doc_class, str) else None
    if schema is None:
        return [Finding(rel, "KB-1", f"unregistered doc_class {doc_class!r}")]
    validator = Draft202012Validator(schema)
    return [
        Finding(
            rel,
            "KB-1",
            f"{'/'.join(str(p) for p in e.absolute_path) or '<front-matter>'}: {e.message}",
        )
        for e in sorted(validator.iter_errors(fm), key=lambda e: list(e.absolute_path))
    ]


def _expected_doc_class(rel_parts: tuple[str, ...]) -> str | None:
    """Machine doc_class a path implies, or None for human-owned paths."""
    name = rel_parts[-1]
    if name == "index.md":
        return "machine-index"
    if name.endswith(".schema.md"):
        return "machine-group" if len(rel_parts) == 3 else "machine-object"
    return None


def _check_path_consistency(rel: str, parts: tuple[str, ...], fm: dict) -> list[Finding]:
    """Front-matter identity must reproduce the file's location (KB §3)."""
    findings = []
    doc_class = fm.get("doc_class")
    sys_dir = parts[1]

    def _sys_mismatch(system: object) -> bool:
        return not isinstance(system, str) or mangle(system) != sys_dir

    if doc_class == "machine-object":
        obj = fm.get("object", "")
        pieces = obj.split(".", 2) if isinstance(obj, str) else []
        if len(pieces) != 3:
            findings.append(Finding(rel, "layout", f"object {obj!r} is not a system.schema.name FQN"))
        else:
            system, schema, name = pieces
            if _sys_mismatch(system) or (
                len(parts) == 4
                and (mangle(schema) != parts[2] or f"{mangle(name)}.schema.md" != parts[3])
            ):
                findings.append(
                    Finding(rel, "layout", f"object {obj!r} does not map to this path")
                )
        if len(parts) != 4:
            findings.append(
                Finding(rel, "layout", "machine-object docs live at systems/<system>/<schema>/<object>.schema.md")
            )
    elif doc_class == "machine-group":
        stem = parts[-1].removesuffix(".schema.md")
        if len(parts) != 3 or stem not in _GROUP_STEMS:
            findings.append(
                Finding(rel, "layout", "machine-group docs live at systems/<system>/<kind-group>.schema.md")
            )
        else:
            expected_kind = next(k for k, g in KIND_GROUPS.items() if g == stem)
            for entry in fm.get("objects", []):
                if isinstance(entry, dict) and entry.get("kind") != expected_kind:
                    findings.append(
                        Finding(rel, "layout", f"roster kind {entry.get('kind')!r} does not belong in group {stem!r}")
                    )
    elif doc_class == "machine-index":
        scope = fm.get("scope")
        if scope == "system" and len(parts) != 3:
            findings.append(Finding(rel, "layout", "system-scoped index must sit at systems/<system>/index.md"))
        if scope == "schema":
            if len(parts) != 4:
                findings.append(Finding(rel, "layout", "schema-scoped index must sit at systems/<system>/<schema>/index.md"))
            elif isinstance(fm.get("schema"), str) and mangle(fm["schema"]) != parts[2]:
                findings.append(Finding(rel, "layout", f"schema {fm['schema']!r} does not map to directory {parts[2]!r}"))
        if _sys_mismatch(fm.get("system")):
            findings.append(Finding(rel, "layout", f"system {fm.get('system')!r} does not map to directory {sys_dir!r}"))
    return findings


# --------------------------------------------------------------------------
# KB-5 — relative links and anchors resolve (KB §8, §10)

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]*)(?:\s+\"[^\"]*\")?\)")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_LINE = re.compile(r"^ {0,3}(```|~~~)")
_INLINE_LINK_TEXT = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _gfm_slug(heading: str) -> str:
    """GitHub's anchor id for a heading (github-slugger algorithm)."""
    text = _INLINE_LINK_TEXT.sub(r"\1", heading).replace("`", "")
    text = "".join(c for c in text.lower() if c.isalnum() or c in "_- ")
    return text.replace(" ", "-")


def _body_lines_outside_fences(text: str):
    _, body = frontmatter.split(text)
    fence: str | None = None
    for line in body.splitlines():
        m = _FENCE_LINE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
            elif m.group(1) == fence:
                fence = None
            continue
        if fence is None:
            yield line


def _anchors(text: str) -> frozenset[str]:
    slugs: dict[str, int] = {}
    out = []
    for line in _body_lines_outside_fences(text):
        m = _HEADING.match(line)
        if not m:
            continue
        slug = _gfm_slug(m.group(2))
        seen = slugs.get(slug)
        slugs[slug] = 0 if seen is None else seen + 1
        out.append(slug if seen is None else f"{slug}-{slugs[slug]}")
    return frozenset(out)


def _check_links(kb_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    anchor_cache: dict[str, frozenset[str]] = {}

    def anchors_of(rel: str, path: Path) -> frozenset[str]:
        if rel not in anchor_cache:
            anchor_cache[rel] = _anchors(path.read_text(encoding="utf-8", errors="replace"))
        return anchor_cache[rel]

    docs = [
        p
        for p in sorted(kb_dir.rglob("*.md"))
        if not any(part.startswith(".") for part in p.relative_to(kb_dir).parts)
    ]
    for path in docs:
        rel = path.relative_to(kb_dir).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in _body_lines_outside_fences(text):
            for m in _LINK.finditer(line):
                target = m.group(1)
                if _SCHEME.match(target):
                    continue  # external URL / mailto — out of KB-5 scope
                if not target:
                    findings.append(Finding(rel, "KB-5", "empty link target"))
                    continue
                if target.startswith("/"):
                    findings.append(
                        Finding(rel, "KB-5", f"absolute link {target!r} — intra-KB links are relative (§8)")
                    )
                    continue
                dest, _, fragment = target.partition("#")
                fragment = unquote(fragment)
                if dest:
                    dest_rel = posixpath.normpath(
                        posixpath.join(posixpath.dirname(rel), unquote(dest))
                    )
                    if dest_rel.split("/", 1)[0] == "..":
                        findings.append(
                            Finding(rel, "KB-5", f"link {target!r} escapes the KB root")
                        )
                        continue
                    dest_path = kb_dir / dest_rel
                    if not dest_path.exists():
                        findings.append(
                            Finding(rel, "KB-5", f"broken link {target!r}: no such file")
                        )
                        continue
                else:
                    dest_rel, dest_path = rel, path
                if fragment and dest_path.suffix == ".md" and dest_path.is_file():
                    if fragment not in anchors_of(dest_rel, dest_path):
                        findings.append(
                            Finding(rel, "KB-5", f"broken link {target!r}: no such anchor in {dest_rel}")
                        )
    return findings


def validate_tree(
    kb_dir: Path | str, snapshots: list[dict] | None = None
) -> list[Finding]:
    """Validate a KB tree; returns findings (empty = conformant)."""
    kb_dir = Path(kb_dir)
    findings: list[Finding] = []

    if (kb_dir / "faults").exists():
        findings.append(
            Finding("faults", "layout", "faults/ must not exist — the fault ledger is Postgres, not git (KB §3)")
        )

    machine_on_disk: dict[str, dict] = {}
    for path in sorted(kb_dir.rglob("*.md")):
        rel = path.relative_to(kb_dir).as_posix()
        if rel in _ROOT_EXEMPT or path.name == "_notes.md":
            continue  # §4.6 root-bootstrap / K-7 exemption
        parts = tuple(rel.split("/"))
        if parts[0] != "systems":
            continue  # entities/metrics/lineage: classes land with 1.7-1.9
        if len(parts) < 3 or len(parts) > 4:
            findings.append(Finding(rel, "layout", "unexpected nesting under systems/"))
            continue

        fm, _ = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
        fm_findings = _validate_front_matter(rel, fm)
        findings.extend(fm_findings)
        if fm is None:
            continue

        implied = _expected_doc_class(parts)
        doc_class = fm.get("doc_class")
        if implied is not None:
            machine_on_disk[rel] = fm
            if doc_class != implied and not any(f.check == "KB-1" for f in fm_findings):
                findings.append(
                    Finding(rel, "layout", f"path implies doc_class {implied!r}, front-matter says {doc_class!r}")
                )
        elif isinstance(doc_class, str) and doc_class.startswith("machine-"):
            findings.append(
                Finding(rel, "layout", f"{doc_class} front-matter on a human-owned path (K-1)")
            )
        if not fm_findings and implied is not None:
            findings.extend(_check_path_consistency(rel, parts, fm))

    findings.extend(_check_links(kb_dir))
    if snapshots is not None:
        findings.extend(_cross_check(kb_dir, snapshots, machine_on_disk))
    return sorted(findings, key=lambda f: (f.path, f.check, f.message))


def _cross_check(
    kb_dir: Path, snapshots: list[dict], machine_on_disk: dict[str, dict]
) -> list[Finding]:
    findings: list[Finding] = []
    expected: dict[str, dict] = {}
    envelopes: dict[str, dict] = {}
    for snap in snapshots:
        errors, _ = validate_snapshot(snap)
        if errors:
            findings.append(
                Finding("<snapshot>", "provenance", f"invalid snapshot for {snap.get('system', '?')!r}: {errors[0]}")
            )
            continue
        for rel, entry in expected_docs(snap).items():
            expected[rel] = entry
            envelopes[rel] = snap

    for rel in sorted(set(expected) - set(machine_on_disk)):
        findings.append(Finding(rel, "provenance", "machine doc missing for snapshot object (K-8)"))

    checked_systems = {mangle(s["system"]) for s in snapshots}
    for rel in sorted(set(machine_on_disk) - set(expected)):
        if rel.split("/")[1] in checked_systems:
            findings.append(Finding(rel, "provenance", "orphan machine doc — no such object in the snapshot"))

    for rel in sorted(set(expected) & set(machine_on_disk)):
        entry, snap, fm = expected[rel], envelopes[rel], machine_on_disk[rel]
        if fm.get("source_mode") != snap["source_mode"]:
            findings.append(Finding(rel, "provenance", f"source_mode {fm.get('source_mode')!r} != snapshot {snap['source_mode']!r}"))
        if fm.get("snapshot_version") != snap["snapshot_version"]:
            findings.append(Finding(rel, "provenance", f"snapshot_version {fm.get('snapshot_version')!r} != snapshot {snap['snapshot_version']!r}"))
        if entry["doc_class"] == "machine-object":
            for key in ("object", "kind", "schema_hash"):
                if fm.get(key) != entry[key]:
                    findings.append(Finding(rel, "provenance", f"{key} {fm.get(key)!r} != snapshot {entry[key]!r}"))
        elif entry["doc_class"] == "machine-group":
            roster = fm.get("objects")
            if roster != entry["roster"]:
                findings.append(Finding(rel, "provenance", "roster does not match the snapshot's objects for this group"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m generator.validate",
        description="Validate a KB tree: front-matter schemas + layout conformance.",
    )
    parser.add_argument("kb_dir", metavar="KB_DIR")
    parser.add_argument(
        "--snapshot",
        action="append",
        default=[],
        metavar="FILE",
        help="cross-check machine docs against this snapshot (repeatable)",
    )
    args = parser.parse_args(argv)

    snapshots = None
    if args.snapshot:
        snapshots = []
        for path in args.snapshot:
            with open(path, encoding="utf-8") as fh:
                snapshots.append(json.load(fh))

    findings = validate_tree(Path(args.kb_dir), snapshots)
    for f in findings:
        print(f"{f.path}: [{f.check}] {f.message}")
    print(f"{len(findings)} finding{'s' if len(findings) != 1 else ''}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
