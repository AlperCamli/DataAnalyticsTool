"""Emission pipeline: introspection facts → validated canonical snapshot.

Everything here composes the 1.1 snapshot library — hashing,
canonicalization, and schema validation are imported, never
reimplemented. The pipeline is the connector-side mirror of the core's
delivery gate (J-6): a snapshot that would dead-letter downstream must
fail loudly here instead, as `EmissionError` (code `validation_error`,
non-retryable).

Producer-side strictness beyond the consumer-side validator:
- unknown `kind` is an error (S-7: producers emit only registered
  kinds; the skip-with-warning rule S-5 is for consumers),
- unregistered `stats` fields are an error (S-7, conformance C-8),
- a connector-supplied `schema_hash` is verified against the 1.1
  library's recomputation, never trusted (C-4).

The emitted serialization is the §6 canonical form of the full
document (canonical body plus the three per-run envelope fields), so
two runs against the same source state differ only in `captured_at`.
"""

import copy
from dataclasses import dataclass
from datetime import datetime, timezone

from jsonschema import Draft202012Validator, FormatChecker

from snapshot.canonical import CANONICAL_BODY_EXCLUDED, canonical_body, canonical_json
from snapshot.hashing import UnknownKindError, schema_hash
from snapshot.registry import KIND_REGISTRY, registered_stats_fields
from snapshot.validate import validate_snapshot

from connectors.sdk.errors import EmissionError
from connectors.sdk.manifest import SUPPORTED_SNAPSHOT_VERSION, Manifest
from connectors.sdk.providers import IntrospectionResult


@dataclass(frozen=True)
class EmittedSnapshot:
    document: dict  # full snapshot document, canonically ordered
    serialized: bytes  # canonical JSON (§6) + trailing newline


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_objects(objects: list[dict]) -> list[str]:
    """Set every object's schema_hash from the 1.1 library; returns problems."""
    problems: list[str] = []
    for obj in objects:
        label = f"{obj.get('schema', '?')}.{obj.get('name', '?')} ({obj.get('kind', '?')})"
        try:
            computed = schema_hash(obj)
        except UnknownKindError as exc:
            problems.append(str(exc))
            continue
        except (KeyError, TypeError) as exc:
            problems.append(f"{label}: malformed object — {exc!r}")
            continue
        supplied = obj.get("schema_hash")
        if supplied is not None and supplied != computed:
            problems.append(
                f"{label}: connector-supplied schema_hash {supplied} does not "
                f"match recomputed {computed} (C-4)"
            )
        obj["schema_hash"] = computed

        extra = set(obj["stats"]) - registered_stats_fields(obj["kind"])
        if extra:
            problems.append(
                f"{label}: unregistered stats fields {sorted(extra)} — declare "
                "them in the §4.5 registry before emitting (S-7)"
            )
    return problems


def emit_snapshot(
    *,
    manifest: Manifest,
    config: dict,
    result: IntrospectionResult,
    captured_at: str | None = None,
) -> EmittedSnapshot:
    """Assemble, hash, validate, and canonicalize one snapshot.

    Raises EmissionError on any problem; never returns a partial or
    invalid document (S-6: the caller fails the whole job).
    """
    objects = copy.deepcopy(list(result.objects))
    problems = _hash_objects(objects)
    if problems:
        raise EmissionError(problems)

    document = {
        "snapshot_version": SUPPORTED_SNAPSHOT_VERSION,
        "system": config["system"],
        "system_class": result.system_class,
        "source_mode": config["mode"],
        "captured_at": captured_at or utc_now_iso(),
        "connector": {"name": manifest.name, "version": manifest.version},
        "objects": objects,
    }
    if result.source_properties is not None:
        document["source_properties"] = copy.deepcopy(result.source_properties)

    errors, warnings = validate_snapshot(document, check_hashes=True)
    # Consumer-side warnings (unknown kind, S-5) are producer-side errors.
    problems = errors + warnings
    if problems:
        raise EmissionError(problems)

    ordered = canonical_body(document)
    ordered.update({k: document[k] for k in CANONICAL_BODY_EXCLUDED})
    try:
        serialized = canonical_json(ordered).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise EmissionError([f"snapshot is not canonically serializable: {exc}"])
    return EmittedSnapshot(document=ordered, serialized=serialized)


def config_problems(manifest: Manifest, config: object) -> list[str]:
    """Validate a snapshot-job config against the manifest (capability §4/§5).

    Config must satisfy the manifest's config_schema, carry `system`,
    and carry a `mode` among the declared metadata modes (MP-1's "no
    silent fallback" starts with refusing undeclared modes outright).
    """
    if not isinstance(config, dict):
        return ["config must be a JSON object"]
    validator = Draft202012Validator(manifest.config_schema, format_checker=FormatChecker())
    problems = [
        f"config{'/' + '/'.join(str(p) for p in e.absolute_path) if list(e.absolute_path) else ''}: {e.message}"
        for e in sorted(validator.iter_errors(config), key=lambda e: list(e.absolute_path))
    ]
    if not isinstance(config.get("system"), str) or not config.get("system"):
        problems.append("config: 'system' (non-empty string) is required for snapshot jobs")
    modes = manifest.metadata_modes()
    if config.get("mode") not in modes:
        problems.append(
            f"config: 'mode' must be one of the manifest's declared metadata "
            f"modes {list(modes)}, got {config.get('mode')!r}"
        )
    return problems
