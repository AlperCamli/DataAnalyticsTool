"""Renderer: snapshots in → machine-owned KB tree out (task 1.5).

Deterministic and idempotent by construction:

- render is a function of (snapshot set, existing output tree); the tree
  contributes only prior `generated_at` values (D-33 Rule B) and the
  existence/front-matter of human-owned siblings (hot/stub, status
  roll-ups, `_notes.md` links). On an empty output dir it is a pure
  function of the snapshots.
- stored file order is never trusted: objects re-sorted (kind, schema,
  name), columns by ordinal, keys per §6 rule 5 (D-36.6);
- a file whose candidate render equals the existing bytes modulo the
  `generated_at` line is left byte-untouched (KB §4.1 amendment, D-33);
- the machine-owned file set is exactly what the snapshots define:
  vanished objects' machine files are pruned; human-owned files are never
  written or deleted; systems absent from the input are untouched (D-36.3).

Zero model calls, zero network, no wall clock.
"""

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, PackageLoader, StrictUndefined

from generator import frontmatter
from generator.naming import KIND_GROUPS, SQL_KINDS, anchor_id, fqn, mangle
from snapshot.canonical import ordered_object
from snapshot.validate import validate_snapshot

log = logging.getLogger("generator")

DASH = "—"  # — : the "absent fact" marker (D-36.5); never placeholder prose
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_env = Environment(
    loader=PackageLoader("generator", "templates"),
    undefined=StrictUndefined,  # a missing fact fails loudly (D-37)
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


class GeneratorError(Exception):
    """Invalid input or unrenderable estate; nothing is partially written per system."""


@dataclass
class RenderResult:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    bootstrapped: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# cell rendering (D-36.5)


def cell(text: str) -> str:
    """Escape a verbatim string for a markdown table cell (deterministic)."""
    return (
        text.replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "<br>")
        .replace("\n", "<br>")
        .replace("\r", "<br>")
    )


def code(text: str) -> str:
    return f"`{cell(text)}`"


def _opt_cell(value: str | None) -> str:
    return cell(value) if value is not None else DASH


def _code_or_dash(value: str | None) -> str:
    return code(value) if value is not None else DASH


# --------------------------------------------------------------------------
# layout: one source of truth for which machine docs a snapshot defines


def expected_docs(snapshot: dict) -> dict[str, dict]:
    """Machine-doc plan for one snapshot: repo-relative path -> expectation.

    Expectation keys consumed by the validation library: ``doc_class``,
    plus per class ``object``/``kind``/``schema_hash`` (object docs),
    ``roster`` (group docs), ``scope``/``schema`` (indexes). The private
    ``_objects`` key carries the canonically ordered snapshot objects the
    renderer builds bodies from.
    """
    system = snapshot["system"]
    sysdir = f"systems/{mangle(system)}"
    family = SQL_KINDS if snapshot["system_class"] == "sql" else frozenset(KIND_GROUPS)

    objs = [
        ordered_object(o)
        for o in sorted(
            snapshot["objects"], key=lambda o: (o["kind"], o["schema"], o["name"])
        )
    ]
    known = []
    for o in objs:
        if o["kind"] in family:
            known.append(o)
        else:
            log.warning(
                "unknown kind %r for %s.%s — skipped (S-5)",
                o["kind"],
                o["schema"],
                o["name"],
            )

    plan: dict[str, dict] = {}

    def _add(rel: str, entry: dict) -> None:
        if rel in plan:
            raise GeneratorError(
                f"path collision after mangling: {rel!r} (system {system!r}) — "
                "two source-native names map to one file"
            )
        plan[rel] = entry

    if snapshot["system_class"] == "sql":
        schemas: dict[str, list[dict]] = {}
        for o in known:
            schemas.setdefault(o["schema"], []).append(o)
        for o in known:
            _add(
                f"{sysdir}/{mangle(o['schema'])}/{mangle(o['name'])}.schema.md",
                {
                    "doc_class": "machine-object",
                    "object": fqn(system, o["schema"], o["name"]),
                    "kind": o["kind"],
                    "schema_hash": o["schema_hash"],
                    "_objects": [o],
                },
            )
        for schema in sorted(schemas):
            _add(
                f"{sysdir}/{mangle(schema)}/index.md",
                {
                    "doc_class": "machine-index",
                    "scope": "schema",
                    "schema": schema,
                    "_objects": schemas[schema],
                },
            )
    else:
        groups: dict[str, list[dict]] = {}
        for o in known:
            groups.setdefault(KIND_GROUPS[o["kind"]], []).append(o)
        for group in sorted(groups):
            members = groups[group]
            _add(
                f"{sysdir}/{group}.schema.md",
                {
                    "doc_class": "machine-group",
                    "roster": [
                        {
                            "object": fqn(system, o["schema"], o["name"]),
                            "kind": o["kind"],
                            "schema_hash": o["schema_hash"],
                        }
                        for o in members
                    ],
                    "_objects": members,
                },
            )
    _add(
        f"{sysdir}/index.md",
        {"doc_class": "machine-index", "scope": "system", "_objects": known},
    )
    return plan


# --------------------------------------------------------------------------
# human-owned sibling reads (hot/stub, status roll-up — K-8)


def _human_info(path: Path) -> tuple[bool, str | None]:
    """(exists, status) for a human-owned doc; unparseable front-matter
    reads as no status — reporting that is KB-1's job, not the index's."""
    if not path.is_file():
        return False, None
    fm, _ = frontmatter.split(path.read_text(encoding="utf-8", errors="replace"))
    status = fm.get("status") if isinstance(fm, dict) else None
    return True, status if isinstance(status, str) else None


# --------------------------------------------------------------------------
# body builders (facts verbatim-or-absent, S-8; structure only)


def _column_rows(columns: list[dict]) -> list[dict]:
    return [
        {
            "ordinal": c["ordinal"],
            "name": cell(c["name"]),
            "type": cell(c["type"]),
            "nullable": "true" if c["nullable"] else "false",
            "default": _code_or_dash(c["default"]),
            "description": _opt_cell(c["description"]),
        }
        for c in columns
    ]


def _sql_object_context(
    system: str, obj: dict, all_objects: list[dict]
) -> dict:
    keys = obj["keys"]
    identities = {(o["schema"], o["name"]) for o in all_objects}

    def _href(target_schema: str, target_name: str) -> str:
        stem = f"{mangle(target_name)}.schema.md"
        if target_schema == obj["schema"]:
            return stem
        return f"../{mangle(target_schema)}/{stem}"

    foreign = []
    for fk in keys.get("foreign", []):
        ref_schema, ref_name = fk["ref"].split(".", 1)
        if (ref_schema, ref_name) in identities:
            ref = f"[`{cell(fk['ref'])}`]({_href(ref_schema, ref_name)})"
        else:
            ref = code(fk["ref"])
        foreign.append(
            {
                "columns": ", ".join(code(c) for c in fk["columns"]),
                "ref": ref,
                "ref_columns": ", ".join(code(c) for c in fk["ref_columns"]),
            }
        )

    referenced_by = []
    target = f"{obj['schema']}.{obj['name']}"
    for other in all_objects:
        for fk in other["keys"].get("foreign", []):
            if fk["ref"] == target:
                referenced_by.append(
                    {
                        "fqn": cell(fqn(system, other["schema"], other["name"])),
                        "href": _href(other["schema"], other["name"]),
                        "via": ", ".join(code(c) for c in fk["columns"]),
                    }
                )

    stats = obj["stats"]
    row_estimate = stats.get("row_estimate")
    return {
        "fqn": fqn(system, obj["schema"], obj["name"]),
        "kind": obj["kind"],
        "schema_hash": obj["schema_hash"],
        "description": obj["description"],
        "columns": _column_rows(obj["columns"]),
        "primary": ", ".join(code(c) for c in keys.get("primary", [])) or DASH,
        "foreign": foreign,
        "unique": [
            ", ".join(code(c) for c in group) for group in keys.get("unique", [])
        ],
        "indexes": [cell(i) for i in stats.get("indexes", [])],
        "row_estimate": str(row_estimate) if row_estimate is not None else DASH,
        "referenced_by": referenced_by,
        "definition": (
            stats.get("definition")
            if obj["kind"] in ("view", "materialized_view")
            else None
        ),
    }


_FACT_LABELS = [
    ("data_type", "Data type", False),
    ("scope", "Scope", False),
    ("formula", "Formula", True),
]


def _group_context(system: str, group: str, members: list[dict]) -> dict:
    rendered = []
    for o in members:
        stats = o["stats"]
        fact_rows = []
        for key, label, as_code in _FACT_LABELS:
            if key in stats:
                value = str(stats[key])
                fact_rows.append(
                    {"label": label, "value": code(value) if as_code else cell(value)}
                )
        if "is_key_event" in stats:
            fact_rows.append(
                {
                    "label": "Key event",
                    "value": "true" if stats["is_key_event"] else "false",
                }
            )
        rendered.append(
            {
                "anchor": anchor_id(o["schema"], o["name"]),
                "name": cell(o["name"]),
                "fqn": fqn(system, o["schema"], o["name"]),
                "kind": o["kind"],
                "namespace": cell(o["schema"]),
                "fact_rows": fact_rows,
                "schema_hash": o["schema_hash"],
                "description": o["description"],
                "parameters": _column_rows(o["columns"]),
            }
        )
    count = len(members)
    return {
        "system": system,
        "group": group,
        "summary": f"{count} object{'s' if count != 1 else ''}.",
        "members": rendered,
    }


def _schema_index_context(
    system: str, schema: str, members: list[dict], schema_dir: Path
) -> dict:
    rows = []
    hot = 0
    for o in members:
        stem = mangle(o["name"])
        exists, status = _human_info(schema_dir / f"{stem}.md")
        if exists:
            hot += 1
        rows.append(
            {
                "name": cell(o["name"]),
                "kind": o["kind"],
                "machine": f"{stem}.schema.md",
                "human": f"[{stem}.md]({stem}.md)" if exists else DASH,
                "status": cell(status) if status else DASH,
            }
        )
    count = len(members)
    return {
        "system": system,
        "schema": cell(schema),
        "summary": (
            f"{count} object{'s' if count != 1 else ''} · {hot} with human docs."
        ),
        "rows": rows,
    }


def _source_properties_json(snapshot: dict) -> str | None:
    props = snapshot.get("source_properties")
    if not props:
        return None
    return json.dumps(props, sort_keys=True, indent=2, ensure_ascii=False)


def _system_index_context(snapshot: dict, known: list[dict], sysdir: Path) -> dict:
    system = snapshot["system"]
    has_notes = (sysdir / "_notes.md").is_file()
    if snapshot["system_class"] == "sql":
        schemas: dict[str, list[dict]] = {}
        for o in known:
            schemas.setdefault(o["schema"], []).append(o)
        rows = []
        for schema in sorted(schemas):
            members = schemas[schema]
            human_count = sum(
                1
                for o in members
                if _human_info(sysdir / mangle(schema) / f"{mangle(o['name'])}.md")[0]
            )
            rows.append(
                {
                    "schema": cell(schema),
                    "count": len(members),
                    "human_count": human_count,
                    "href": f"{mangle(schema)}/index.md",
                }
            )
        n_schemas = len(schemas)
        summary = (
            f"{len(known)} object{'s' if len(known) != 1 else ''} across "
            f"{n_schemas} schema{'s' if n_schemas != 1 else ''}."
        )
    else:
        groups: dict[str, list[dict]] = {}
        for o in known:
            groups.setdefault(KIND_GROUPS[o["kind"]], []).append(o)
        rows = []
        for group in sorted(groups):
            members = groups[group]
            exists, status = _human_info(sysdir / f"{group}.md")
            rows.append(
                {
                    "group": group,
                    "kind": members[0]["kind"],
                    "count": len(members),
                    "machine": f"{group}.schema.md",
                    "human": f"[{group}.md]({group}.md)" if exists else DASH,
                    "status": cell(status) if status else DASH,
                }
            )
        n_groups = len(groups)
        summary = (
            f"{len(known)} object{'s' if len(known) != 1 else ''} across "
            f"{n_groups} group{'s' if n_groups != 1 else ''}."
        )
    return {
        "system": system,
        "summary": summary,
        "has_notes": has_notes,
        "rows": rows,
        "source_properties": _source_properties_json(snapshot),
    }


# --------------------------------------------------------------------------
# front-matter field builders (fixed key order per class — KB §4)


def _provenance(date: str, snapshot: dict) -> list[tuple[str, Any]]:
    return [
        ("generated_at", date),
        ("source_mode", snapshot["source_mode"]),
        ("snapshot_version", snapshot["snapshot_version"]),
        ("status", "machine"),
    ]


def _fields_fn(entry: dict, snapshot: dict) -> Callable[[str], list[tuple[str, Any]]]:
    doc_class = entry["doc_class"]
    system = snapshot["system"]

    def fields(date: str) -> list[tuple[str, Any]]:
        if doc_class == "machine-object":
            head: list[tuple[str, Any]] = [
                ("doc_class", "machine-object"),
                ("object", entry["object"]),
                ("kind", entry["kind"]),
                ("schema_hash", entry["schema_hash"]),
            ]
        elif doc_class == "machine-group":
            head = [("doc_class", "machine-group"), ("objects", entry["roster"])]
        else:
            head = [("doc_class", "machine-index"), ("system", system)]
            head.append(("scope", entry["scope"]))
            if entry["scope"] == "schema":
                head.append(("schema", entry["schema"]))
        return head + _provenance(date, snapshot)

    return fields


# --------------------------------------------------------------------------
# writing (D-33 Rule B) and pruning (D-36.3)


def _write_machine(
    path: Path,
    rel: str,
    fields: Callable[[str], list[tuple[str, Any]]],
    body: str,
    new_date: str,
    result: RenderResult,
) -> None:
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="replace")
        fm, _ = frontmatter.split(old)
        old_date = fm.get("generated_at") if isinstance(fm, dict) else None
        if isinstance(old_date, str) and _DATE.match(old_date):
            if frontmatter.emit(fields(old_date)) + "\n" + body == old:
                result.unchanged.append(rel)
                return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((frontmatter.emit(fields(new_date)) + "\n" + body).encode("utf-8"))
    result.written.append(rel)


def _is_machine_file(path: Path) -> bool:
    return path.name == "index.md" or path.name.endswith(".schema.md")


def _prune_system(
    out_dir: Path, system: str, keep: set[str], result: RenderResult
) -> None:
    sysdir = out_dir / "systems" / mangle(system)
    if not sysdir.is_dir():
        return
    for path in sorted(sysdir.rglob("*")):
        if path.is_file() and _is_machine_file(path):
            rel = path.relative_to(out_dir).as_posix()
            if rel not in keep:
                path.unlink()
                result.deleted.append(rel)
    for d in sorted((p for p in sysdir.rglob("*") if p.is_dir()), reverse=True):
        try:
            d.rmdir()  # only empties fall
        except OSError:
            pass


# --------------------------------------------------------------------------
# top level


def _render_system(out_dir: Path, snapshot: dict, result: RenderResult) -> None:
    system = snapshot["system"]
    sysdir = out_dir / "systems" / mangle(system)
    new_date = snapshot["captured_at"][:10]
    plan = expected_docs(snapshot)

    for rel in sorted(plan):
        entry = plan[rel]
        members = entry["_objects"]
        if entry["doc_class"] == "machine-object":
            # all known objects of the system feed Referenced-by
            body = _env.get_template("object_schema.md.j2").render(
                o=_sql_object_context(system, members[0], _known_sql(snapshot))
            )
        elif entry["doc_class"] == "machine-group":
            group = Path(rel).name.removesuffix(".schema.md")
            body = _env.get_template("group_schema.md.j2").render(
                g=_group_context(system, group, members)
            )
        elif entry["scope"] == "schema":
            body = _env.get_template("index_schema.md.j2").render(
                i=_schema_index_context(
                    system, entry["schema"], members, sysdir / mangle(entry["schema"])
                )
            )
        else:
            template = (
                "index_system_sql.md.j2"
                if snapshot["system_class"] == "sql"
                else "index_system_api.md.j2"
            )
            body = _env.get_template(template).render(
                s=_system_index_context(snapshot, members, sysdir)
            )
        _write_machine(
            out_dir / rel, rel, _fields_fn(entry, snapshot), body, new_date, result
        )

    _prune_system(out_dir, system, set(plan), result)


def _known_sql(snapshot: dict) -> list[dict]:
    return [
        ordered_object(o)
        for o in sorted(
            snapshot["objects"], key=lambda o: (o["kind"], o["schema"], o["name"])
        )
        if o["kind"] in SQL_KINDS
    ]


def _bootstrap(out_dir: Path, snapshots: dict[str, dict], result: RenderResult) -> None:
    """K-7: root index.md + conventions.md, written only when absent."""
    index = out_dir / "index.md"
    if not index.exists():
        systems = [
            {"name": name, "href": f"systems/{mangle(name)}/index.md"}
            for name in sorted(snapshots)
        ]
        content = _env.get_template("root_index.md.j2").render(systems=systems)
        index.write_bytes(content.encode("utf-8"))
        result.bootstrapped.append("index.md")
    conventions = out_dir / "conventions.md"
    if not conventions.exists():
        content = _env.get_template("conventions.md.j2").render()
        conventions.write_bytes(content.encode("utf-8"))
        result.bootstrapped.append("conventions.md")


def render_tree(snapshots: list[dict], out_dir: Path | str) -> RenderResult:
    """Render the machine-owned KB tree for the given snapshots.

    Raises GeneratorError on invalid input; never partially validates.
    Systems not present in ``snapshots`` are left untouched (system
    removal is administrative, snapshot spec §7).
    """
    out_dir = Path(out_dir)
    by_system: dict[str, dict] = {}
    for snap in snapshots:
        errors, warnings = validate_snapshot(snap)
        if errors:
            name = snap.get("system", "<unknown>")
            raise GeneratorError(
                f"invalid snapshot for system {name!r}: " + "; ".join(errors)
            )
        for warning in warnings:
            log.warning("%s", warning)
        system = snap["system"]
        if system in by_system:
            raise GeneratorError(f"duplicate system {system!r} in inputs")
        by_system[system] = snap

    out_dir.mkdir(parents=True, exist_ok=True)
    result = RenderResult()
    for system in sorted(by_system):
        _render_system(out_dir, by_system[system], result)
    _bootstrap(out_dir, by_system, result)
    for bucket in (result.written, result.unchanged, result.deleted):
        bucket.sort()
    return result


# --------------------------------------------------------------------------
# CLI — task 1.6 runs this against the customer repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m generator.render",
        description="Render snapshot file(s) into a KB repo tree (machine-owned files only).",
    )
    parser.add_argument(
        "snapshots", nargs="+", metavar="SNAPSHOT", help="snapshot JSON file(s)"
    )
    parser.add_argument("--out", required=True, metavar="DIR", help="KB repo root")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        snaps = []
        for path in args.snapshots:
            with open(path, encoding="utf-8") as fh:
                snaps.append(json.load(fh))
        result = render_tree(snaps, Path(args.out))
    except (GeneratorError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"written {len(result.written)} · unchanged {len(result.unchanged)} · "
        f"deleted {len(result.deleted)} · bootstrapped {len(result.bootstrapped)}"
    )
    if args.verbose:
        for label, bucket in (
            ("written", result.written),
            ("deleted", result.deleted),
            ("bootstrapped", result.bootstrapped),
        ):
            for rel in bucket:
                print(f"  {label}: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
