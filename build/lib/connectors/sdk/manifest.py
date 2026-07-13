"""Connector manifest loading and validation (capability spec §3, CC-1).

A connector ships a `connector.yaml` declaring identity (name + semver
version), the protocol/snapshot versions it speaks, its capabilities, a
JSON Schema for `payload.config`, credential requirements (vault
references only, job spec J-4), and its quota policy (`rate_limit`).

`load_manifest` enforces the CC-1 pieces a file can carry: the manifest
validates structurally, every declared capability maps to a job type
(job spec §4.2), the SDK supports the declared protocol/snapshot
versions, and `config_schema` resolves (relative to the manifest) to a
valid Draft 2020-12 JSON Schema. The remaining CC-1 clause — each
declared capability has a registered handler — is code, not file, and
is checked at `Connector` assembly (connector.py).
"""

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

# SDK support pins (capability spec CI-E: the manifest declares all
# three versions; the SDK pins what it can honor per release).
SUPPORTED_PROTOCOL_VERSION = 1
SUPPORTED_SNAPSHOT_VERSION = "1"

# Capability → job type (job spec §4.2 registry). Growth is additive.
CAPABILITY_JOB_TYPES: dict[str, str] = {
    "metadata": "snapshot",
    "query": "execute",
    "usage": "usage",
    "knowledge": "harvest",
    "publish": "publish",
    "lineage": "lineage",
}


class ManifestError(Exception):
    """Manifest failed validation; `problems` lists every finding."""

    def __init__(self, path: Path, problems: list[str]):
        self.path = path
        self.problems = problems
        joined = "\n  ".join(problems)
        super().__init__(f"invalid connector manifest {path}:\n  {joined}")


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    protocol_version: int
    snapshot_version: str
    capabilities: dict[str, dict]
    config_schema: dict
    credentials: tuple[dict, ...]
    rate_limit: dict
    health_probe: str | None
    path: Path
    config_schema_path: Path

    def metadata_modes(self) -> tuple[str, ...]:
        """Declared MetadataProvider modes; empty if metadata undeclared."""
        return tuple(self.capabilities.get("metadata", {}).get("modes", ()))


def _manifest_schema() -> dict:
    ref = resources.files("connectors.sdk") / "schema" / "manifest.v1.schema.json"
    return json.loads(ref.read_text(encoding="utf-8"))


def load_manifest(path: str | Path) -> Manifest:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(path, [f"unreadable: {exc}"]) from exc
    except yaml.YAMLError as exc:
        raise ManifestError(path, [f"not valid YAML: {exc}"]) from exc
    if not isinstance(raw, dict):
        raise ManifestError(path, ["top level must be a mapping"])

    validator = Draft202012Validator(_manifest_schema())
    problems = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    ]
    if problems:
        raise ManifestError(path, problems)

    if raw["protocol_version"] != SUPPORTED_PROTOCOL_VERSION:
        problems.append(
            f"protocol_version {raw['protocol_version']} unsupported "
            f"(this SDK pins protocol version {SUPPORTED_PROTOCOL_VERSION}, job spec §9)"
        )
    if raw["snapshot_version"] != SUPPORTED_SNAPSHOT_VERSION:
        problems.append(
            f"snapshot_version {raw['snapshot_version']!r} unsupported "
            f"(this SDK emits snapshot_version {SUPPORTED_SNAPSHOT_VERSION!r})"
        )
    for capability in raw["capabilities"]:
        if capability not in CAPABILITY_JOB_TYPES:
            problems.append(
                f"capability {capability!r} has no job type in the §4.2 registry "
                f"(known: {', '.join(sorted(CAPABILITY_JOB_TYPES))})"
            )

    config_schema_path = (path.parent / raw["config_schema"]).resolve()
    config_schema: dict = {}
    try:
        config_schema = json.loads(config_schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(config_schema)
    except OSError as exc:
        problems.append(f"config_schema {raw['config_schema']!r}: unreadable ({exc})")
    except json.JSONDecodeError as exc:
        problems.append(f"config_schema {raw['config_schema']!r}: not valid JSON ({exc})")
    except SchemaError as exc:
        problems.append(
            f"config_schema {raw['config_schema']!r}: not a valid Draft 2020-12 "
            f"JSON Schema ({exc.message})"
        )

    if problems:
        raise ManifestError(path, problems)

    return Manifest(
        name=raw["name"],
        version=raw["version"],
        protocol_version=raw["protocol_version"],
        snapshot_version=raw["snapshot_version"],
        capabilities=raw["capabilities"],
        config_schema=config_schema,
        credentials=tuple(raw.get("credentials", ())),
        rate_limit=raw["rate_limit"],
        health_probe=raw.get("health_probe"),
        path=path,
        config_schema_path=config_schema_path,
    )
