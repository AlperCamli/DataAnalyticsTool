"""Normalized metadata snapshot layer (snapshot_version "1").

Implements spec/snapshot-schema-spec.md: canonical serialization (§6),
schema_hash (§5), diff semantics (§7), and the §8.1 JSON Schema.
Ambiguity rulings are recorded in DECISIONS.md (D-0..D-9).
"""

from snapshot.canonical import (
    canonical_body,
    canonical_body_bytes,
    canonical_json,
    canonical_object_bytes,
)
from snapshot.diff import DiffError, diff_snapshots
from snapshot.hashing import UnknownKindError, schema_hash, structural_projection
from snapshot.registry import KIND_REGISTRY, registered_stats_fields

__all__ = [
    "KIND_REGISTRY",
    "DiffError",
    "UnknownKindError",
    "canonical_body",
    "canonical_body_bytes",
    "canonical_json",
    "canonical_object_bytes",
    "diff_snapshots",
    "registered_stats_fields",
    "schema_hash",
    "structural_projection",
]
