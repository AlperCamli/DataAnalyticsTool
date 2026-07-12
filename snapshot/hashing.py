"""schema_hash computation (spec §5).

Hash input is the canonical JSON of the object's structural projection:
kind/schema/name, columns reduced to {name, type, nullable, default,
ordinal} (descriptions excluded), keys complete, and only hash-included
§4.5 stats fields. Projection shape per DECISIONS.md D-4: stats stay
nested (empty {} when none), keys carried verbatim after §6 ordering.
"""

import hashlib

from snapshot.canonical import canonical_json, ordered_keys
from snapshot.registry import KIND_REGISTRY

COLUMN_STRUCTURAL_FIELDS = ("name", "type", "nullable", "default", "ordinal")


class UnknownKindError(KeyError):
    """Raised when hashing an object whose kind has no registry entry.

    Producers may only emit registered kinds (S-7); consumers encountering
    an unknown kind skip it with a warning instead (S-5) — they never hash.
    """


def structural_projection(obj: dict) -> dict:
    kind = obj["kind"]
    spec = KIND_REGISTRY.get(kind)
    if spec is None:
        raise UnknownKindError(
            f"kind {kind!r} is not in the v1 registry; register its stats "
            "fields (spec §4.5) before emitting it"
        )
    return {
        "kind": kind,
        "schema": obj["schema"],
        "name": obj["name"],
        "columns": [
            {f: c[f] for f in COLUMN_STRUCTURAL_FIELDS}
            for c in sorted(obj["columns"], key=lambda c: c["ordinal"])
        ],
        "keys": ordered_keys(obj["keys"]),
        "stats": {
            k: v for k, v in obj["stats"].items() if k in spec.hash_included_stats
        },
    }


def schema_hash(obj: dict) -> str:
    digest = hashlib.sha256(
        canonical_json(structural_projection(obj)).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"
