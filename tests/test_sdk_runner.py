"""Runner engine + emission pipeline, exercised through the static demo
and through fake connectors staging producer bugs.

Harness-level renderings of the conformance suite: C-1/C-4 (emitted
snapshot validates, hashes recompute), C-2 (byte-identical reruns),
C-7/S-6 (mid-introspection failure → failed job, nothing emitted),
CC-2's shape (declared-mode-unavailable → source_unavailable), J-5
(quota defers, never fails), J-6 connector-side (invalid snapshot →
validation_error before anything is delivered), MP-1 (source_mode
stamped from config.mode), S-7/C-8 (unregistered kinds/stats refused).
"""

import copy
import datetime
import json

import pytest

from connectors.sdk import Connector, IntrospectionResult, Job, QueryExecutor, run_job
from connectors.static_demo.connector import _emails_view, _users_table
from connectors.static_demo.connector import connector as demo_connector
from snapshot.canonical import canonical_body_bytes, canonical_json
from snapshot.hashing import schema_hash
from snapshot.validate import validate_snapshot
from tests.conftest import FakeMetadata, make_connector, write_manifest

DEMO_CONFIG = {"system": "demo", "mode": "ddl-file"}


def run_demo(config=None, **kwargs):
    return run_job(demo_connector, Job.local(config or dict(DEMO_CONFIG)), **kwargs)


def sql_result(objects, source_properties=None):
    return IntrospectionResult(
        system_class="sql", objects=objects, source_properties=source_properties
    )


# --- success path ---


def test_success_emits_valid_snapshot():
    outcome = run_demo()
    assert outcome.status == "succeeded"
    assert outcome.error is None
    doc = outcome.snapshot.document
    assert validate_snapshot(doc, check_hashes=True) == ([], [])  # C-1 + C-4
    assert doc["snapshot_version"] == "1"
    assert doc["system"] == "demo"
    assert doc["source_mode"] == DEMO_CONFIG["mode"]  # MP-1
    assert doc["connector"] == {"name": "static-demo", "version": "0.1.0"}
    assert [o["name"] for o in doc["objects"]] == ["users", "v_user_emails"]


def test_serialized_form_is_canonical_json():
    outcome = run_demo()
    serialized = outcome.snapshot.serialized
    assert serialized == canonical_json(outcome.snapshot.document).encode("utf-8") + b"\n"
    assert json.loads(serialized) == outcome.snapshot.document


def test_c2_reruns_byte_identical():
    first, second = run_demo(), run_demo()
    assert canonical_body_bytes(first.snapshot.document) == canonical_body_bytes(
        second.snapshot.document
    )
    pinned = "2026-07-12T00:00:00Z"
    a = run_demo(captured_at=pinned)
    b = run_demo(captured_at=pinned)
    assert a.snapshot.serialized == b.snapshot.serialized


def test_connector_supplied_correct_hash_accepted(tmp_path):
    table = _users_table()
    table["schema_hash"] = schema_hash(table)
    connector = make_connector(tmp_path, lambda c: sql_result([table]))
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert outcome.status == "succeeded"
    assert outcome.snapshot.document["objects"][0]["schema_hash"] == table["schema_hash"]


# --- config gate (config_error, non-retryable) ---


@pytest.mark.parametrize(
    "config",
    [
        {"mode": "ddl-file"},  # system missing
        {"system": "demo", "mode": "live"},  # mode not declared in manifest
        {"system": "demo", "mode": "ddl-file", "surprise": 1},  # schema: additionalProperties
        {"system": "", "mode": "ddl-file"},  # system empty
    ],
)
def test_config_rejected(config):
    outcome = run_demo(config)
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.error.retryable is False
    assert outcome.snapshot is None


def test_undeclared_mode_message_names_declared_modes():
    outcome = run_demo({"system": "demo", "mode": "live"})
    assert "ddl-file" in outcome.error.message and "'live'" in outcome.error.message


# --- failure taxonomy + S-6 all-or-nothing (C-7) ---


def test_c7_mid_introspection_failure_emits_nothing():
    outcome = run_demo({**DEMO_CONFIG, "inject_failure": "source_unavailable"})
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"
    assert outcome.error.retryable is True
    assert outcome.snapshot is None  # never a one-object partial snapshot


def test_bare_exception_maps_to_internal_with_traceback():
    outcome = run_demo({**DEMO_CONFIG, "inject_failure": "internal"})
    assert outcome.status == "failed"
    assert outcome.error.code == "internal"
    assert outcome.error.retryable is True
    assert "RuntimeError" in outcome.error.message
    assert "traceback" in outcome.error.detail
    assert outcome.snapshot is None


def test_error_message_and_traceback_redact_credentials(tmp_path):
    # F3 / D-66 point 2: a driver exception that echoes the resolved DSN must
    # not carry the secret into JobError — the scrub runs before it is built.
    from connectors.sdk.redact import REDACTION_MARKER

    canary = "cl-canary-run-4d2a9f"
    dsn = f"postgres://svc:{canary}@db.internal:5432/appdb"

    def boom(config):
        raise RuntimeError(f"could not connect to {dsn}")

    outcome = run_job(make_connector(tmp_path, boom), Job.local(dict(DEMO_CONFIG)))
    assert outcome.status == "failed"
    assert outcome.error.code == "internal"
    assert canary not in outcome.error.message
    assert REDACTION_MARKER in outcome.error.message
    traceback_text = outcome.error.detail["traceback"]
    assert canary not in traceback_text
    assert REDACTION_MARKER in traceback_text


def test_j5_quota_is_deferral_not_failure():
    outcome = run_demo({**DEMO_CONFIG, "inject_failure": "quota"})
    assert outcome.status == "deferred"
    assert outcome.retry_after_s == 3600
    assert outcome.error.code == "quota"
    assert outcome.snapshot is None


def test_wrong_return_type_is_internal(tmp_path):
    connector = make_connector(tmp_path, lambda c: {"objects": []})
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert outcome.status == "failed"
    assert outcome.error.code == "internal"
    assert "IntrospectionResult" in outcome.error.message


# --- emission gate (validation_error, non-retryable — J-6 connector-side) ---


def assert_validation_error(outcome, needle):
    assert outcome.status == "failed"
    assert outcome.error.code == "validation_error"
    assert outcome.error.retryable is False
    assert outcome.snapshot is None
    assert needle in outcome.error.message


def test_unknown_kind_refused(tmp_path):
    table = _users_table()
    table["kind"] = "warp_table"
    connector = make_connector(tmp_path, lambda c: sql_result([table]))
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "not in the v1 registry")


def test_unregistered_stats_field_refused(tmp_path):
    table = _users_table()
    table["stats"]["definition"] = "SELECT 1"  # registered for views, not tables
    connector = make_connector(tmp_path, lambda c: sql_result([table]))
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "unregistered stats fields")


def test_connector_supplied_wrong_hash_refused(tmp_path):
    table = _users_table()
    table["schema_hash"] = "sha256:" + "0" * 64
    connector = make_connector(tmp_path, lambda c: sql_result([table]))
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "does not match recomputed")


def test_duplicate_identity_refused(tmp_path):
    table = _users_table()
    connector = make_connector(
        tmp_path, lambda c: sql_result([table, copy.deepcopy(table)])
    )
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "duplicate object identity")


def test_malformed_object_refused(tmp_path):
    table = _users_table()
    del table["columns"]
    connector = make_connector(tmp_path, lambda c: sql_result([table]))
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "malformed object")


def test_invalid_system_class_refused(tmp_path):
    connector = make_connector(
        tmp_path,
        lambda c: IntrospectionResult(system_class="graphql", objects=[_users_table()]),
    )
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "system_class")


def test_non_serializable_value_refused(tmp_path):
    connector = make_connector(
        tmp_path,
        lambda c: sql_result(
            [_emails_view()], source_properties={"when": datetime.datetime(2026, 7, 12)}
        ),
    )
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert_validation_error(outcome, "not canonically serializable")


# --- engine dispatch ---


class _StubExecutor(QueryExecutor):
    def execute(self, config, request, guardrails, identity):  # pragma: no cover
        raise AssertionError("not reached: this connector declares no metadata capability")


def test_metadata_capability_undeclared_is_config_error(tmp_path):
    path = write_manifest(
        tmp_path, {"capabilities": {"query": {"dialect": "postgresql"}}}
    )
    connector = Connector(path, {"query": _StubExecutor()})
    outcome = run_job(connector, Job.local(dict(DEMO_CONFIG)))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert "metadata capability" in outcome.error.message


def test_unsupported_job_type_raises():
    with pytest.raises(ValueError, match="harvest"):
        run_job(demo_connector, Job(job_id="j", config={}, type="harvest"))


# --- the builtin health probe (A-3, job type `test_connection`) ---


def probe(connector, config):
    return run_job(connector, Job(job_id="p", config=config, type="test_connection"))


def test_probe_reports_unprobed_rather_than_a_pass_it_did_not_perform():
    """The honesty rule: the static demo declares metadata and implements
    no preflight, so the probe succeeds *and says it exercised nothing*.
    A green tick beside a source nobody has ever read is the failure this
    whole checkpoint exists to prevent."""
    outcome = probe(demo_connector, dict(DEMO_CONFIG))
    assert outcome.status == "succeeded"
    assert outcome.result["ok"] is True
    assert outcome.result["unprobed"] == ["metadata"]
    statuses = {c["capability"]: c["status"] for c in outcome.result["checks"]}
    assert statuses == {"config": "pass", "metadata": "unprobed"}


def test_probe_runs_the_config_gate_first():
    outcome = probe(demo_connector, {"system": "demo", "mode": "nonsense"})
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.error.retryable is False


def test_probe_maps_a_refused_credential_to_auth_error(tmp_path):
    """`auth_error` is what the Connections module turns into a re-auth
    prompt, so the mapping from the connector's own exception to the
    outer taxonomy is load-bearing rather than cosmetic."""
    from connectors.sdk import AuthError

    class Refusing(FakeMetadata):
        def preflight(self, config):
            raise AuthError("the source refused these credentials")

    connector = Connector(
        write_manifest(tmp_path), {"metadata": Refusing(lambda config: sql_result([]))}
    )
    outcome = probe(connector, dict(DEMO_CONFIG))
    assert outcome.status == "failed"
    assert outcome.error.code == "auth_error"
    assert outcome.error.retryable is False
    assert outcome.error.detail["capability"] == "metadata"
    assert outcome.error.detail["checks"][-1]["status"] == "fail"


def test_probe_scrubs_credentials_out_of_its_own_report(tmp_path):
    """A probe exists to touch credentials, so its report is the one
    place a resolved DSN would most plausibly leak (JC-8/F3)."""

    class Leaky(FakeMetadata):
        def preflight(self, config):
            return {"probed": True, "dsn": "postgres://u:hunter2@h/db"}

    connector = Connector(
        write_manifest(tmp_path), {"metadata": Leaky(lambda config: sql_result([]))}
    )
    outcome = probe(connector, dict(DEMO_CONFIG))
    assert outcome.status == "succeeded"
    assert "hunter2" not in json.dumps(outcome.result)
