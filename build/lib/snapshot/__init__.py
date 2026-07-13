"""Normalized metadata snapshot layer (snapshot_version "1").

Implements spec/snapshot-schema-spec.md: canonical serialization (§6),
schema_hash (§5), diff semantics (§7), and the §8.1 JSON Schema.
Ambiguity rulings are recorded in DECISIONS.md (D-0..D-9).

Exports are lazy (PEP 562) so `python -m snapshot.<module>` CLIs do not
re-import the module being executed.
"""

from importlib import import_module

_EXPORTS = {
    "canonical_body": "snapshot.canonical",
    "canonical_body_bytes": "snapshot.canonical",
    "canonical_json": "snapshot.canonical",
    "canonical_object_bytes": "snapshot.canonical",
    "DiffError": "snapshot.diff",
    "diff_snapshots": "snapshot.diff",
    "UnknownKindError": "snapshot.hashing",
    "schema_hash": "snapshot.hashing",
    "structural_projection": "snapshot.hashing",
    "KIND_REGISTRY": "snapshot.registry",
    "registered_stats_fields": "snapshot.registry",
    "load_schema": "snapshot.validate",
    "validate_snapshot": "snapshot.validate",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
