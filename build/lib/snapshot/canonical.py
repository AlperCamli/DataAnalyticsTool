"""Canonical serialization and ordering (spec §6).

The canonical form makes S-3 (idempotency) and S-4 (mode invariance)
byte-testable: compact JSON, UTF-8, keys sorted lexicographically at every
nesting level, `objects` by (kind, schema, name), `columns` by ordinal,
`keys.foreign` by (columns joined, ref), `keys.unique` lexicographic.
Column lists inside keys keep source-declared order (§6 rule 5).

Canonical body := envelope minus `captured_at`, `connector`, and
`source_mode` — the third exclusion is DECISIONS.md D-1: S-4 and §8.2
require mode-different snapshots to be canonical-body-identical, which the
§3 two-exclusion wording cannot satisfy.
"""

import json
from typing import Any

CANONICAL_BODY_EXCLUDED = ("captured_at", "connector", "source_mode")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def ordered_keys(keys: dict) -> dict:
    out = dict(keys)
    if "foreign" in out:
        out["foreign"] = sorted(
            out["foreign"], key=lambda fk: (",".join(fk["columns"]), fk["ref"])
        )
    if "unique" in out:
        out["unique"] = sorted(out["unique"])
    return out


def ordered_object(obj: dict) -> dict:
    out = dict(obj)
    out["columns"] = sorted(obj["columns"], key=lambda c: c["ordinal"])
    out["keys"] = ordered_keys(obj["keys"])
    return out


def canonical_object_bytes(obj: dict) -> bytes:
    """Per-object canonical bytes — the §7 'bodies byte-equal' comparison."""
    return canonical_json(ordered_object(obj)).encode("utf-8")


def canonical_body(snapshot: dict) -> dict:
    body = {k: v for k, v in snapshot.items() if k not in CANONICAL_BODY_EXCLUDED}
    body["objects"] = [
        ordered_object(o)
        for o in sorted(
            snapshot["objects"], key=lambda o: (o["kind"], o["schema"], o["name"])
        )
    ]
    return body


def canonical_body_bytes(snapshot: dict) -> bytes:
    return canonical_json(canonical_body(snapshot)).encode("utf-8")
