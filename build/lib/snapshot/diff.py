"""Snapshot diff engine (spec §7).

Compares two snapshots of the same system by object identity (S-1) and
classifies each object as added / removed / changed-structural (with a
field-level sub-diff) / changed-metadata-only / unchanged. Severities per
the §7 table; anything hash-affecting that the table does not name is
breaking (DECISIONS.md D-2). The footnote-3 downgrade of definition
changes needs lineage and is deferred to the sync engine — such sub-diffs
carry downgradable=True (D-3). Unknown kinds are skipped with a logged
warning (S-5). Input contract details in D-6.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from snapshot.canonical import canonical_object_bytes
from snapshot.hashing import schema_hash
from snapshot.registry import KIND_REGISTRY

logger = logging.getLogger("snapshot.diff")

ADDITIVE = "additive"
ADDITIVE_WITH_NOTE = "additive-with-note"
BREAKING = "breaking"
_SEVERITY_RANK = {ADDITIVE: 1, ADDITIVE_WITH_NOTE: 2, BREAKING: 3}

_ABSENT = object()


class DiffError(ValueError):
    pass


Identity = tuple[str, str, str]  # (kind, schema, name); system is snapshot-level


@dataclass
class SubDiff:
    change: str
    severity: str
    detail: dict
    downgradable: bool = False

    def to_dict(self) -> dict:
        out = {"change": self.change, "severity": self.severity, "detail": self.detail}
        if self.downgradable:
            out["downgradable"] = True
        return out


@dataclass
class RenameCandidate:
    """Footnote 1: removed + added column sharing type and ordinal.

    Not directly observable, so both interpretations (rename vs
    remove+add) are surfaced in the drift changelog; the removal remains
    breaking either way.
    """

    from_column: str
    to_column: str
    type: str
    ordinal: int

    def to_dict(self) -> dict:
        return {
            "from_column": self.from_column,
            "to_column": self.to_column,
            "type": self.type,
            "ordinal": self.ordinal,
            "interpretations": ["column renamed", "column removed + column added"],
        }


@dataclass
class ObjectDiff:
    identity: Identity
    classification: str  # added | removed | changed_structural | changed_metadata_only
    severity: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None
    sub_diffs: list[SubDiff] = field(default_factory=list)
    rename_candidates: list[RenameCandidate] = field(default_factory=list)
    metadata_changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        kind, schema, name = self.identity
        out: dict[str, Any] = {
            "identity": {"kind": kind, "schema": schema, "name": name},
            "classification": self.classification,
        }
        if self.severity is not None:
            out["severity"] = self.severity
        if self.old_hash is not None:
            out["old_hash"] = self.old_hash
        if self.new_hash is not None:
            out["new_hash"] = self.new_hash
        if self.sub_diffs:
            out["sub_diffs"] = [s.to_dict() for s in self.sub_diffs]
        if self.rename_candidates:
            out["rename_candidates"] = [r.to_dict() for r in self.rename_candidates]
        if self.metadata_changes:
            out["metadata_changes"] = self.metadata_changes
        return out


@dataclass
class SnapshotDiff:
    system: str
    added: list[ObjectDiff] = field(default_factory=list)
    removed: list[ObjectDiff] = field(default_factory=list)
    changed_structural: list[ObjectDiff] = field(default_factory=list)
    changed_metadata_only: list[ObjectDiff] = field(default_factory=list)
    unchanged: list[Identity] = field(default_factory=list)
    skipped_unknown_kinds: list[Identity] = field(default_factory=list)
    source_properties_changed: bool = False  # informational, not a §7 class (D-6e)

    def is_empty(self) -> bool:
        return not (
            self.added
            or self.removed
            or self.changed_structural
            or self.changed_metadata_only
        )

    def to_dict(self) -> dict:
        return {
            "system": self.system,
            "empty": self.is_empty(),
            "added": [d.to_dict() for d in self.added],
            "removed": [d.to_dict() for d in self.removed],
            "changed_structural": [d.to_dict() for d in self.changed_structural],
            "changed_metadata_only": [d.to_dict() for d in self.changed_metadata_only],
            "unchanged": [
                {"kind": k, "schema": s, "name": n} for (k, s, n) in self.unchanged
            ],
            "skipped_unknown_kinds": [
                {"kind": k, "schema": s, "name": n}
                for (k, s, n) in self.skipped_unknown_kinds
            ],
            "source_properties_changed": self.source_properties_changed,
        }


def _index_objects(
    snapshot: dict, skipped: list[Identity]
) -> dict[Identity, dict]:
    index: dict[Identity, dict] = {}
    for obj in snapshot["objects"]:
        identity: Identity = (obj["kind"], obj["schema"], obj["name"])
        if obj["kind"] not in KIND_REGISTRY:
            if identity not in skipped:
                logger.warning(
                    "skipping object with unknown kind %r: %s.%s (S-5)",
                    obj["kind"], obj["schema"], obj["name"],
                )
                skipped.append(identity)
            continue
        if identity in index:
            raise DiffError(
                f"duplicate object identity {identity} in snapshot of "
                f"system {snapshot['system']!r} (S-1 requires uniqueness)"
            )
        index[identity] = obj
    return index


def _max_severity(sub_diffs: list[SubDiff]) -> str:
    return max((s.severity for s in sub_diffs), key=_SEVERITY_RANK.__getitem__)


def _column_sub_diffs(
    old: dict, new: dict
) -> tuple[list[SubDiff], list[RenameCandidate]]:
    old_cols = {c["name"]: c for c in old["columns"]}
    new_cols = {c["name"]: c for c in new["columns"]}
    subs: list[SubDiff] = []

    added = [new_cols[n] for n in new_cols if n not in old_cols]
    removed = [old_cols[n] for n in old_cols if n not in new_cols]

    for col in added:
        subs.append(SubDiff("column_added", ADDITIVE, {
            "column": col["name"], "type": col["type"],
            "nullable": col["nullable"], "ordinal": col["ordinal"],
        }))
    for col in removed:
        subs.append(SubDiff("column_removed", BREAKING, {
            "column": col["name"], "type": col["type"], "ordinal": col["ordinal"],
        }))

    for name in old_cols.keys() & new_cols.keys():
        o, n = old_cols[name], new_cols[name]
        if o["type"] != n["type"]:
            subs.append(SubDiff("column_type_changed", BREAKING, {
                "column": name, "from": o["type"], "to": n["type"],
            }))
        if o["nullable"] != n["nullable"]:
            if o["nullable"] and not n["nullable"]:
                subs.append(SubDiff("column_nullable_tightened", BREAKING, {
                    "column": name, "from": True, "to": False,
                }))
            else:
                subs.append(SubDiff("column_nullable_loosened", ADDITIVE_WITH_NOTE, {
                    "column": name, "from": False, "to": True,
                }))
        if o["default"] != n["default"]:
            subs.append(SubDiff("column_default_changed", ADDITIVE_WITH_NOTE, {
                "column": name, "from": o["default"], "to": n["default"],
            }))
        if o["ordinal"] != n["ordinal"]:
            # Not in the §7 severity table; breaking per D-2.
            subs.append(SubDiff("column_ordinal_changed", BREAKING, {
                "column": name, "from": o["ordinal"], "to": n["ordinal"],
            }))

    candidates = [
        RenameCandidate(r["name"], a["name"], r["type"], r["ordinal"])
        for r in removed
        for a in added
        if r["type"] == a["type"] and r["ordinal"] == a["ordinal"]
    ]
    return subs, candidates


def _key_sub_diffs(old: dict, new: dict) -> list[SubDiff]:
    subs: list[SubDiff] = []
    old_keys, new_keys = old["keys"], new["keys"]

    old_pk = old_keys.get("primary") or []
    new_pk = new_keys.get("primary") or []
    if old_pk != new_pk:
        if not old_pk:
            subs.append(SubDiff("key_added", ADDITIVE,
                                {"key": "primary", "columns": new_pk}))
        elif not new_pk:
            subs.append(SubDiff("key_removed", BREAKING,
                                {"key": "primary", "columns": old_pk}))
        else:
            subs.append(SubDiff("key_altered", BREAKING,
                                {"key": "primary", "from": old_pk, "to": new_pk}))

    old_fks = {tuple(fk["columns"]): fk for fk in old_keys.get("foreign") or []}
    new_fks = {tuple(fk["columns"]): fk for fk in new_keys.get("foreign") or []}
    for cols in new_fks.keys() - old_fks.keys():
        subs.append(SubDiff("key_added", ADDITIVE,
                            {"key": "foreign", **new_fks[cols]}))
    for cols in old_fks.keys() - new_fks.keys():
        subs.append(SubDiff("key_removed", BREAKING,
                            {"key": "foreign", **old_fks[cols]}))
    for cols in old_fks.keys() & new_fks.keys():
        if old_fks[cols] != new_fks[cols]:
            subs.append(SubDiff("key_altered", BREAKING, {
                "key": "foreign", "columns": list(cols),
                "from": old_fks[cols], "to": new_fks[cols],
            }))

    old_uq = {tuple(u) for u in old_keys.get("unique") or []}
    new_uq = {tuple(u) for u in new_keys.get("unique") or []}
    for cols in sorted(new_uq - old_uq):
        subs.append(SubDiff("key_added", ADDITIVE,
                            {"key": "unique", "columns": list(cols)}))
    for cols in sorted(old_uq - new_uq):
        subs.append(SubDiff("key_removed", BREAKING,
                            {"key": "unique", "columns": list(cols)}))
    return subs


def _stats_sub_diffs(old: dict, new: dict) -> list[SubDiff]:
    subs: list[SubDiff] = []
    included = KIND_REGISTRY[old["kind"]].hash_included_stats
    for stat in sorted(included):
        o = old["stats"].get(stat, _ABSENT)
        n = new["stats"].get(stat, _ABSENT)
        if o is n or o == n:
            continue
        detail = {
            "stat": stat,
            "from": None if o is _ABSENT else o,
            "to": None if n is _ABSENT else n,
            "was_absent": o is _ABSENT,
            "now_absent": n is _ABSENT,
        }
        if stat == "definition":
            # Breaking pending the footnote-3 lineage downgrade (D-3).
            subs.append(SubDiff("definition_changed", BREAKING, detail,
                                downgradable=True))
        else:
            # data_type/scope/formula breaking per §7; is_key_event and
            # field appearance/disappearance breaking per D-2.
            subs.append(SubDiff("stat_changed", BREAKING, detail))
    return subs


def _metadata_changes(old: dict, new: dict) -> list[str]:
    changes: list[str] = []
    if old["description"] != new["description"]:
        changes.append("description")
    old_cols = {c["name"]: c for c in old["columns"]}
    new_cols = {c["name"]: c for c in new["columns"]}
    for name in sorted(old_cols.keys() & new_cols.keys()):
        if old_cols[name]["description"] != new_cols[name]["description"]:
            changes.append(f"columns.{name}.description")
    excluded = KIND_REGISTRY[old["kind"]].hash_excluded_stats
    for stat in sorted(excluded):
        if old["stats"].get(stat, _ABSENT) != new["stats"].get(stat, _ABSENT):
            changes.append(f"stats.{stat}")
    return changes


def diff_object(old: dict, new: dict) -> ObjectDiff:
    """Classify one identity present in both snapshots."""
    identity: Identity = (old["kind"], old["schema"], old["name"])
    if old["schema_hash"] != new["schema_hash"]:
        subs, candidates = _column_sub_diffs(old, new)
        subs += _key_sub_diffs(old, new)
        subs += _stats_sub_diffs(old, new)
        return ObjectDiff(
            identity, "changed_structural",
            severity=_max_severity(subs) if subs else BREAKING,
            old_hash=old["schema_hash"], new_hash=new["schema_hash"],
            sub_diffs=subs, rename_candidates=candidates,
        )
    if canonical_object_bytes(old) != canonical_object_bytes(new):
        return ObjectDiff(
            identity, "changed_metadata_only",
            old_hash=old["schema_hash"], new_hash=new["schema_hash"],
            metadata_changes=_metadata_changes(old, new),
        )
    return ObjectDiff(identity, "unchanged")


def diff_snapshots(
    old: dict, new: dict, *, verify_hashes: bool = False
) -> SnapshotDiff:
    if old["system"] != new["system"]:
        raise DiffError(
            f"cannot diff snapshots of different systems: "
            f"{old['system']!r} vs {new['system']!r} (§7)"
        )
    if verify_hashes:
        for snap in (old, new):
            for obj in snap["objects"]:
                if obj["kind"] not in KIND_REGISTRY:
                    continue
                recomputed = schema_hash(obj)
                if recomputed != obj["schema_hash"]:
                    raise DiffError(
                        f"stored schema_hash for {obj['schema']}.{obj['name']} "
                        f"({obj['kind']}) does not match recomputation "
                        f"(C-4 violation): {obj['schema_hash']} != {recomputed}"
                    )

    result = SnapshotDiff(system=old["system"])
    old_index = _index_objects(old, result.skipped_unknown_kinds)
    new_index = _index_objects(new, result.skipped_unknown_kinds)

    for identity in sorted(new_index.keys() - old_index.keys()):
        obj = new_index[identity]
        result.added.append(ObjectDiff(
            identity, "added", severity=ADDITIVE, new_hash=obj["schema_hash"],
        ))
    for identity in sorted(old_index.keys() - new_index.keys()):
        obj = old_index[identity]
        result.removed.append(ObjectDiff(
            identity, "removed", severity=BREAKING, old_hash=obj["schema_hash"],
        ))
    for identity in sorted(old_index.keys() & new_index.keys()):
        diff = diff_object(old_index[identity], new_index[identity])
        if diff.classification == "changed_structural":
            result.changed_structural.append(diff)
        elif diff.classification == "changed_metadata_only":
            result.changed_metadata_only.append(diff)
        else:
            result.unchanged.append(identity)

    result.source_properties_changed = (
        old.get("source_properties", {}) != new.get("source_properties", {})
    )
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m snapshot.diff",
        description="Diff two snapshots of the same system (spec §7).",
    )
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument("--verify-hashes", action="store_true",
                        help="recompute every schema_hash first (C-4 check)")
    args = parser.parse_args(argv)

    try:
        with open(args.old, encoding="utf-8") as f:
            old = json.load(f)
        with open(args.new, encoding="utf-8") as f:
            new = json.load(f)
        result = diff_snapshots(old, new, verify_hashes=args.verify_hashes)
    except (OSError, json.JSONDecodeError, DiffError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
