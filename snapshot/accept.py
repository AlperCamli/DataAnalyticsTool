"""Delivery-gate CLI — validate + canonicalize a delivered snapshot (J-6).

    python -m snapshot.accept BODY.json [--key result] --out CANONICAL.json

The core job API shells out to this on every snapshot delivery instead
of reimplementing validation or canonicalization in TypeScript (CP-3a
ruling C1: the Python implementations stay the single source of truth).
It is a thin composition of the existing 1.1 pieces — `validate_snapshot`
(schema + S-1 + C-4 hash recomputation) and the §6 canonical
serialization exactly as `connectors.sdk.emission` builds it — no new
logic.

`--key` selects a top-level member of the input file (the §6.4 complete
body carries the document under `result`); without it the file is the
document itself. On success the canonical serialization is written to
`--out`, so the stored accepted snapshot is byte-identical to what the
emitting SDK produced for the same document (the JS layer never
re-serializes JSON).

stdout carries exactly one JSON verdict line:

    {"valid": true,  "warnings": [...], "system": ..., "snapshot_version":
     ..., "source_mode": ..., "captured_at": ..., "connector": {...},
     "object_count": N, "sha256": ..., "canonical_body_sha256": ...}
    {"valid": false, "errors": [...], "warnings": [...]}

Unknown kinds stay warnings here (S-5: this is the consumer side; the
producer-side strictness lives in emission). Exit codes: 0 valid,
1 invalid, 2 usage/environment error.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from snapshot.canonical import (
    CANONICAL_BODY_EXCLUDED,
    canonical_body,
    canonical_body_bytes,
    canonical_json,
)
from snapshot.validate import validate_snapshot

EXIT_VALID, EXIT_INVALID, EXIT_USAGE = 0, 1, 2


def canonical_document_bytes(document: dict) -> bytes:
    """§6 canonical form of the full document — mirrors emission exactly."""
    ordered = canonical_body(document)
    ordered.update({k: document[k] for k in CANONICAL_BODY_EXCLUDED})
    return canonical_json(ordered).encode("utf-8") + b"\n"


def accept(document: object) -> tuple[dict, bytes | None]:
    """Returns (verdict, canonical bytes or None if invalid)."""
    if not isinstance(document, dict):
        return {
            "valid": False,
            "errors": [f"delivered result must be a JSON object, got {type(document).__name__}"],
            "warnings": [],
        }, None
    errors, warnings = validate_snapshot(document, check_hashes=True)
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}, None
    serialized = canonical_document_bytes(document)
    verdict = {
        "valid": True,
        "warnings": warnings,
        "system": document["system"],
        "snapshot_version": document["snapshot_version"],
        "source_mode": document["source_mode"],
        "captured_at": document["captured_at"],
        "connector": document["connector"],
        "object_count": len(document["objects"]),
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "canonical_body_sha256": hashlib.sha256(canonical_body_bytes(document)).hexdigest(),
    }
    return verdict, serialized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m snapshot.accept",
        description="Validate a delivered snapshot (J-6) and write its "
        "canonical serialization.",
    )
    parser.add_argument("file", metavar="FILE", help="delivered JSON body")
    parser.add_argument("--key", metavar="NAME",
                        help="top-level member of FILE holding the snapshot "
                        "document (e.g. 'result' for a §6.4 complete body)")
    parser.add_argument("--out", metavar="FILE",
                        help="where to write the canonical serialization on success")
    args = parser.parse_args(argv)

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"cannot read {args.file}: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except json.JSONDecodeError as exc:
        print(json.dumps({"valid": False, "errors": [f"body is not valid JSON: {exc}"],
                          "warnings": []}))
        return EXIT_INVALID

    if args.key is not None:
        if not isinstance(data, dict) or args.key not in data:
            print(json.dumps({"valid": False,
                              "errors": [f"body has no {args.key!r} member"],
                              "warnings": []}))
            return EXIT_INVALID
        data = data[args.key]

    verdict, serialized = accept(data)
    if verdict["valid"] and args.out:
        Path(args.out).write_bytes(serialized)
    print(json.dumps(verdict))
    return EXIT_VALID if verdict["valid"] else EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
