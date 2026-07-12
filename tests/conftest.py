import copy
import json
from pathlib import Path

import pytest
import yaml

from connectors.sdk import Connector, MetadataProvider
from snapshot.hashing import schema_hash

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

FIXTURE_FILES = [
    "supabase-ddl.json",
    "supabase-live.json",
    "ga4.json",
    "gsc.json",
    "drift-pair/before.json",
    "drift-pair/after.json",
]


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def supabase() -> dict:
    return load_fixture("supabase-ddl.json")


@pytest.fixture
def ga4() -> dict:
    return load_fixture("ga4.json")


def find_object(snapshot: dict, name: str) -> dict:
    return next(o for o in snapshot["objects"] if o["name"] == name)


def mutate(snapshot: dict, name: str, fn, *, rehash: bool = True) -> dict:
    """Deep-copy a snapshot, apply fn to the named object, and (like an
    honest producer) recompute that object's schema_hash."""
    out = copy.deepcopy(snapshot)
    obj = find_object(out, name)
    fn(obj)
    if rehash:
        obj["schema_hash"] = schema_hash(obj)
    return out


# --- connector SDK harness helpers (test_sdk_*.py) ---

SDK_BASE_MANIFEST = {
    "name": "testconn",
    "version": "0.1.0",
    "protocol_version": 1,
    "snapshot_version": "1",
    "capabilities": {"metadata": {"modes": ["ddl-file"]}},
    "config_schema": "./config.schema.json",
    "rate_limit": {"strategy": "none"},
}

SDK_CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["system", "mode"],
    "properties": {"system": {"type": "string"}, "mode": {"type": "string"}},
}


def write_manifest(
    tmp_path: Path,
    overrides: dict | None = None,
    *,
    drop: tuple[str, ...] = (),
    config_schema: dict | None = SDK_CONFIG_SCHEMA,
    config_schema_text: str | None = None,
) -> Path:
    """Write a connector.yaml (+ config schema) into tmp_path."""
    data = {**SDK_BASE_MANIFEST, **(overrides or {})}
    for key in drop:
        data.pop(key, None)
    path = tmp_path / "connector.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    schema_path = tmp_path / "config.schema.json"
    if config_schema_text is not None:
        schema_path.write_text(config_schema_text, encoding="utf-8")
    elif config_schema is not None:
        schema_path.write_text(json.dumps(config_schema), encoding="utf-8")
    return path


class FakeMetadata(MetadataProvider):
    """introspect delegates to a callable(config) that returns or raises."""

    def __init__(self, fn):
        self._fn = fn

    def introspect(self, config: dict):
        return self._fn(config)


def make_connector(tmp_path: Path, introspect_fn) -> Connector:
    return Connector(write_manifest(tmp_path), {"metadata": FakeMetadata(introspect_fn)})
