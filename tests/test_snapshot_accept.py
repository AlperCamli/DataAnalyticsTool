"""The J-6 delivery gate (snapshot/accept.py, CP-3a ruling C1).

The load-bearing property: for a snapshot produced by the SDK's emission
pipeline, accepting the delivered document re-produces the emitted
canonical serialization byte-for-byte — including when the document
travels inside a §6.4 complete body (`--key result`). That property is
what makes core-accepted snapshots byte-identical to local CLI harness
output (the exit criterion pairing C-2 with the transport).
"""

import copy
import json
import subprocess
import sys

import pytest

from connectors.sdk import Job, run_job
from connectors.static_demo.connector import connector as demo_connector
from snapshot.accept import accept, canonical_document_bytes

DEMO_CONFIG = {"system": "demo", "mode": "ddl-file"}


@pytest.fixture(scope="module")
def emitted():
    outcome = run_job(demo_connector, Job.local(dict(DEMO_CONFIG)))
    assert outcome.status == "succeeded"
    return outcome.snapshot


def run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "snapshot.accept", *args],
        capture_output=True, text=True, timeout=60,
    )


def test_accept_reproduces_emitted_bytes(emitted):
    verdict, serialized = accept(json.loads(emitted.serialized))
    assert verdict["valid"] is True
    assert serialized == emitted.serialized
    assert verdict["system"] == "demo"
    assert verdict["object_count"] == 2
    assert verdict["warnings"] == []


def test_cli_complete_body_roundtrip(tmp_path, emitted):
    """§6.4 body with the canonical bytes spliced in as `result`."""
    body = b'{"lease_token":"tok-1","result":' + emitted.serialized.strip() + b"}"
    body_file = tmp_path / "body.json"
    body_file.write_bytes(body)
    out_file = tmp_path / "canonical.json"
    proc = run_cli([str(body_file), "--key", "result", "--out", str(out_file)])
    assert proc.returncode == 0, proc.stderr
    verdict = json.loads(proc.stdout)
    assert verdict["valid"] is True
    assert verdict["connector"] == {"name": "static-demo", "version": "0.1.0"}
    assert out_file.read_bytes() == emitted.serialized


def test_invalid_hash_rejected(tmp_path, emitted):
    doc = json.loads(emitted.serialized)
    doc["objects"][0]["schema_hash"] = "sha256:" + "0" * 64
    body_file = tmp_path / "body.json"
    body_file.write_text(json.dumps(doc), encoding="utf-8")
    out_file = tmp_path / "canonical.json"
    proc = run_cli([str(body_file), "--out", str(out_file)])
    assert proc.returncode == 1
    verdict = json.loads(proc.stdout)
    assert verdict["valid"] is False
    assert any("schema_hash mismatch" in e for e in verdict["errors"])
    assert not out_file.exists()


def test_schema_invalid_rejected():
    verdict, serialized = accept({"snapshot_version": "1"})
    assert verdict["valid"] is False
    assert serialized is None
    assert verdict["errors"]


def test_non_object_rejected():
    verdict, serialized = accept(["not", "a", "snapshot"])
    assert verdict["valid"] is False
    assert serialized is None


def test_unknown_kind_is_warning_not_error(emitted):
    """S-5: consumer side skips unknown kinds with a warning."""
    doc = json.loads(emitted.serialized)
    stranger = copy.deepcopy(doc["objects"][0])
    stranger["kind"] = "materialized_series"
    stranger["name"] = "zz_stranger"
    doc["objects"].append(stranger)
    verdict, serialized = accept(doc)
    assert verdict["valid"] is True
    assert any("unknown kind" in w for w in verdict["warnings"])
    assert serialized is not None


def test_missing_key_is_invalid(tmp_path):
    body_file = tmp_path / "body.json"
    body_file.write_text('{"lease_token": "t"}', encoding="utf-8")
    proc = run_cli([str(body_file), "--key", "result"])
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["valid"] is False


def test_malformed_json_is_invalid(tmp_path):
    body_file = tmp_path / "body.json"
    body_file.write_text("{nope", encoding="utf-8")
    proc = run_cli([str(body_file)])
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["valid"] is False


def test_canonical_document_bytes_matches_emission(emitted):
    assert canonical_document_bytes(emitted.document) == emitted.serialized
