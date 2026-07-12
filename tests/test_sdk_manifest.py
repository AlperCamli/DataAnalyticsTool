"""Manifest contract (capability spec §3, conformance CC-1).

CC-1 has two halves: the file validates (structure, versions, valid
config_schema) — load_manifest; and every declared capability has a
registered handler — Connector assembly. Both fail loudly with every
finding listed, since the manifest is the connector's release gate.
"""

from pathlib import Path

import pytest

from connectors.sdk import (
    Connector,
    ManifestError,
    RegistrationError,
    load_manifest,
)
from tests.conftest import FakeMetadata, write_manifest

DEMO_MANIFEST = (
    Path(__file__).resolve().parent.parent / "connectors" / "static_demo" / "connector.yaml"
)


def test_cc1_static_demo_manifest_loads():
    m = load_manifest(DEMO_MANIFEST)
    assert m.name == "static-demo"
    assert m.version == "0.1.0"
    assert m.protocol_version == 1
    assert m.snapshot_version == "1"
    assert m.metadata_modes() == ("ddl-file",)
    assert m.rate_limit == {"strategy": "none"}
    assert m.credentials == ()
    assert m.config_schema["required"] == ["system", "mode"]


def test_missing_required_field_fails(tmp_path):
    path = write_manifest(tmp_path, drop=("rate_limit",))
    with pytest.raises(ManifestError, match="rate_limit"):
        load_manifest(path)


def test_all_problems_reported_at_once(tmp_path):
    path = write_manifest(tmp_path, drop=("rate_limit", "name"))
    with pytest.raises(ManifestError) as exc:
        load_manifest(path)
    assert len(exc.value.problems) == 2


def test_unknown_capability_fails(tmp_path):
    path = write_manifest(
        tmp_path,
        {"capabilities": {"metadata": {"modes": ["ddl-file"]}, "teleport": {}}},
    )
    with pytest.raises(ManifestError, match="teleport.*no job type"):
        load_manifest(path)


def test_unsupported_protocol_version_fails(tmp_path):
    path = write_manifest(tmp_path, {"protocol_version": 2})
    with pytest.raises(ManifestError, match="protocol_version 2 unsupported"):
        load_manifest(path)


def test_unsupported_snapshot_version_fails(tmp_path):
    path = write_manifest(tmp_path, {"snapshot_version": "2"})
    with pytest.raises(ManifestError, match="snapshot_version '2' unsupported"):
        load_manifest(path)


def test_metadata_mode_outside_enum_fails(tmp_path):
    path = write_manifest(
        tmp_path, {"capabilities": {"metadata": {"modes": ["carrier-pigeon"]}}}
    )
    with pytest.raises(ManifestError, match="carrier-pigeon"):
        load_manifest(path)


def test_unknown_rate_limit_strategy_fails(tmp_path):
    path = write_manifest(tmp_path, {"rate_limit": {"strategy": "vibes"}})
    with pytest.raises(ManifestError, match="vibes"):
        load_manifest(path)


def test_config_schema_file_missing_fails(tmp_path):
    path = write_manifest(tmp_path, config_schema=None)
    with pytest.raises(ManifestError, match="unreadable"):
        load_manifest(path)


def test_config_schema_not_json_fails(tmp_path):
    path = write_manifest(tmp_path, config_schema_text="{nope")
    with pytest.raises(ManifestError, match="not valid JSON"):
        load_manifest(path)


def test_config_schema_not_a_json_schema_fails(tmp_path):
    path = write_manifest(tmp_path, config_schema={"type": "definitely-not"})
    with pytest.raises(ManifestError, match="not a valid Draft 2020-12"):
        load_manifest(path)


def test_yaml_top_level_not_mapping_fails(tmp_path):
    path = tmp_path / "connector.yaml"
    path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="mapping"):
        load_manifest(path)


def test_unparsable_yaml_fails(tmp_path):
    path = tmp_path / "connector.yaml"
    path.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid YAML"):
        load_manifest(path)


# --- CC-1 second half: declared capabilities ↔ registered handlers ---


def test_declared_capability_without_handler_fails(tmp_path):
    with pytest.raises(RegistrationError, match="'metadata'.*no registered handler"):
        Connector(write_manifest(tmp_path), {})


def test_handler_for_undeclared_capability_fails(tmp_path):
    handlers = {"metadata": FakeMetadata(lambda c: None), "query": object()}
    with pytest.raises(RegistrationError, match="undeclared capability 'query'"):
        Connector(write_manifest(tmp_path), handlers)


def test_metadata_handler_must_implement_interface(tmp_path):
    with pytest.raises(RegistrationError, match="MetadataProvider"):
        Connector(write_manifest(tmp_path), {"metadata": object()})


def test_connector_accepts_manifest_instance(tmp_path):
    manifest = load_manifest(write_manifest(tmp_path))
    connector = Connector(manifest, {"metadata": FakeMetadata(lambda c: None)})
    assert connector.manifest is manifest
    assert set(connector.handlers) == {"metadata"}
