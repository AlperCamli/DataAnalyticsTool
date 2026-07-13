"""Snapshot validator CLI.

    python -m snapshot.validate [--check-hashes] FILE [FILE ...]

Validates each file against the normative §8.1 JSON Schema (Draft
2020-12, format assertions on), plus the S-1 uniqueness check the schema
cannot express (duplicate object identities). --check-hashes additionally
recomputes every schema_hash (the C-4 check); objects of unknown kind are
skipped there with a warning per S-5. Exit 0 iff every file passes.
"""

import argparse
import json
import sys
from importlib import resources

from jsonschema import Draft202012Validator, FormatChecker

from snapshot.hashing import schema_hash
from snapshot.registry import KIND_REGISTRY


def load_schema() -> dict:
    ref = resources.files("snapshot") / "schema" / "snapshot.v1.schema.json"
    return json.loads(ref.read_text(encoding="utf-8"))


def validate_snapshot(
    snapshot: dict, *, check_hashes: bool = False
) -> tuple[list[str], list[str]]:
    """Returns (errors, warnings); the snapshot is valid iff errors == []."""
    validator = Draft202012Validator(load_schema(), format_checker=FormatChecker())
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(snapshot), key=lambda e: list(e.absolute_path))
    ]
    warnings: list[str] = []
    if errors:
        return errors, warnings

    seen: set[tuple[str, str, str]] = set()
    for obj in snapshot["objects"]:
        identity = (obj["kind"], obj["schema"], obj["name"])
        if identity in seen:
            errors.append(
                f"duplicate object identity (kind={identity[0]}, "
                f"schema={identity[1]}, name={identity[2]}) — S-1 requires uniqueness"
            )
        seen.add(identity)

        if obj["kind"] not in KIND_REGISTRY:
            warnings.append(
                f"unknown kind {obj['kind']!r} for {obj['schema']}.{obj['name']} "
                "— skipped (S-5)"
            )
        elif check_hashes:
            recomputed = schema_hash(obj)
            if recomputed != obj["schema_hash"]:
                errors.append(
                    f"schema_hash mismatch for {obj['schema']}.{obj['name']} "
                    f"({obj['kind']}): stored {obj['schema_hash']}, "
                    f"recomputed {recomputed} (C-4)"
                )
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m snapshot.validate",
        description="Validate snapshot files against the v1 JSON Schema (§8.1).",
    )
    parser.add_argument("files", nargs="+", metavar="FILE")
    parser.add_argument("--check-hashes", action="store_true",
                        help="also recompute every schema_hash (C-4)")
    args = parser.parse_args(argv)

    failed = False
    for path in args.files:
        try:
            with open(path, encoding="utf-8") as f:
                snapshot = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{path}: INVALID — {exc}", file=sys.stderr)
            failed = True
            continue
        errors, warnings = validate_snapshot(snapshot, check_hashes=args.check_hashes)
        for warning in warnings:
            print(f"{path}: warning — {warning}", file=sys.stderr)
        if errors:
            failed = True
            print(f"{path}: INVALID", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
        else:
            print(f"{path}: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
