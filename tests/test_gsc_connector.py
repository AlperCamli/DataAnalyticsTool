"""GSC connector on recorded API responses, plus the env-gated live pull.

Connector-level renderings of the conformance suite: C-1/C-4 via the
emission gate, C-2 (byte-identical reruns on recordings), C-8 (only
registered stats), J-5 (persistent throttling → deferral, never
failure), MP-1/CC-2 (auth failure / unverified property → taxonomy
failure, job fails, nothing written — including the CLI's no-file
contract). The fixed schema is additionally pinned to the 1.1 fixture:
identities and `schema_hash`es of `fixtures/gsc.json` must be
reproduced exactly (D-30's hash-constancy claim, and a tripwire on the
data_type vocabulary).

The recordings (tests/data/gsc/) are wire-shaped `sites.get` bodies —
the single GET this connector performs — plus canned Google error
bodies for the failure taxonomy.
"""

import copy
import json
import os
import random
from pathlib import Path

import pytest

from connectors.gsc.connector import MANIFEST, FIXED_DIMENSIONS, FIXED_METRICS, GscMetadata
from connectors.gsc.executor import GscExecutor
from connectors.sdk import Connector, Job, run_job
from connectors.sdk.local import main as local_main
from snapshot.canonical import canonical_body_bytes
from snapshot.registry import registered_stats_fields
from snapshot.validate import validate_snapshot

from tests.conftest import load_fixture

RECORDINGS = Path(__file__).resolve().parent / "data" / "gsc"

SITE = "sc-domain:acmestore.com"
CONFIG = {
    "system": "gsc",
    "mode": "api",
    "site_url": SITE,
    "credentials_env": "GSC_SA_JSON",  # never resolved: tests inject the transport
}


def load_recording(name: str) -> dict:
    return json.loads((RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))


class CannedTransport:
    """Always returns the same canned (status, headers, body)."""

    def __init__(self, status: int, headers: dict | None = None, body: dict | None = None):
        self.status, self.headers, self.body = status, headers or {}, body
        self.calls = 0

    def get(self, url: str, params: dict | None = None):
        self.calls += 1
        return self.status, dict(self.headers), copy.deepcopy(self.body)


class FlakyTransport(CannedTransport):
    """Fails the first `failures` calls with `error_status`, then recovers."""

    def __init__(self, failures: int, error_status: int, body: dict | None = None):
        super().__init__(200, body=body or load_recording("site_owner"))
        self.remaining, self.error_status = failures, error_status

    def get(self, url: str, params: dict | None = None):
        if self.remaining > 0:
            self.remaining -= 1
            self.calls += 1
            return self.error_status, {}, None
        return super().get(url, params)


def make_connector(transport) -> Connector:
    provider = GscMetadata(
        transport_factory=lambda config: transport,
        sleep=lambda seconds: None,  # tests never really sleep
        rng=random.Random(7),
    )
    return Connector(manifest=MANIFEST, handlers={"metadata": provider, "query": GscExecutor()})


def run_recorded(transport=None, **kwargs):
    transport = transport or CannedTransport(200, body=load_recording("site_owner"))
    return run_job(make_connector(transport), Job.local(dict(CONFIG)), **kwargs)


def run_ok(transport=None, **kwargs) -> dict:
    outcome = run_recorded(transport, **kwargs)
    assert outcome.status == "succeeded", outcome.error
    return outcome.snapshot.document


def objects_by_identity(document: dict) -> dict:
    return {(o["kind"], o["name"]): o for o in document["objects"]}


# --- success path: fixed schema + envelope (C-1/C-4 via the gate) ---


def test_snapshot_validates_with_reproducible_hashes():
    errors, warnings = validate_snapshot(run_ok(), check_hashes=True)
    assert errors == [] and warnings == []


def test_c2_recorded_reruns_byte_identical():
    assert canonical_body_bytes(run_ok()) == canonical_body_bytes(run_ok())


def test_fixed_estate_identities():
    expected = {("api_dimension", name) for name in FIXED_DIMENSIONS} | {
        ("api_metric", name) for name, _ in FIXED_METRICS
    }
    assert set(objects_by_identity(run_ok())) == expected


def test_fixed_objects_are_constants_with_null_descriptions():
    expected_types = dict(FIXED_METRICS) | {name: "string" for name in FIXED_DIMENSIONS}
    for (_, name), obj in objects_by_identity(run_ok()).items():
        assert obj["schema"] == "standard", name
        assert obj["description"] is None, name  # S-8: doc prose is not a wire fact
        assert obj["columns"] == [] and obj["keys"] == {}, name
        assert obj["stats"] == {"data_type": expected_types[name]}, name


def test_hashes_reproduce_the_11_fixture():
    """D-30: the structural projection is constant, so the connector must
    reproduce fixtures/gsc.json's hashes exactly (descriptions there are
    hand-authored D-7 artifacts — hash-excluded, so they cannot differ)."""
    fixture = {
        (o["kind"], o["name"]): o["schema_hash"]
        for o in load_fixture("gsc.json")["objects"]
    }
    emitted = {
        identity: obj["schema_hash"]
        for identity, obj in objects_by_identity(run_ok()).items()
    }
    assert emitted == fixture


def test_c8_stats_contain_only_registered_fields():
    for obj in run_ok()["objects"]:
        assert set(obj["stats"]) <= registered_stats_fields(obj["kind"])


def test_envelope_and_source_properties():
    document = run_ok()
    assert document["system_class"] == "api"
    assert document["source_mode"] == "api"
    assert document["connector"]["name"] == "gsc"
    assert document["source_properties"] == {
        "properties": [
            {"site_url": SITE, "permission_level": "siteOwner", "verified": True}
        ],
        "data_freshness": {"data_states": ["all", "final"]},
    }


def test_sites_get_is_the_only_call():
    transport = CannedTransport(200, body=load_recording("site_owner"))
    run_ok(transport)
    assert transport.calls == 1


# --- failure taxonomy: job fails, nothing emitted (MP-1/CC-2, S-6) ---


def test_unverified_property_fails_retryable_nothing_emitted():
    outcome = run_recorded(CannedTransport(200, body=load_recording("site_unverified")))
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"
    assert outcome.error.retryable is True
    assert outcome.snapshot is None


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failure_is_auth_error(status):
    outcome = run_recorded(CannedTransport(status, body=load_recording(f"error_{status}")))
    assert outcome.status == "failed"
    assert outcome.error.code == "auth_error"
    assert outcome.error.retryable is False
    assert outcome.snapshot is None


@pytest.mark.parametrize("status", [400, 404])
def test_unknown_property_is_config_error(status):
    body = load_recording("error_404") if status == 404 else None
    outcome = run_recorded(CannedTransport(status, body=body))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.error.retryable is False


def test_failed_job_writes_no_file(tmp_path, monkeypatch):
    import connectors.gsc.connector as gsc_module

    monkeypatch.setattr(
        gsc_module,
        "connector",
        make_connector(CannedTransport(401, body=load_recording("error_401"))),
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(CONFIG), encoding="utf-8")
    out = tmp_path / "snapshot.json"
    rc = local_main(
        ["connectors.gsc.connector", "--config", str(config_path), "--out", str(out)]
    )
    assert rc == 1
    assert not out.exists()


# --- quota and server faults (J-5, D-32) ---


def test_persistent_throttling_defers_with_retry_after():
    transport = CannedTransport(
        429, headers={"Retry-After": "120"}, body=load_recording("error_429")
    )
    outcome = run_recorded(transport)
    assert outcome.status == "deferred"
    assert outcome.retry_after_s == 120
    policy_retries = MANIFEST.rate_limit["max_retries"]
    assert transport.calls == policy_retries + 1


def test_persistent_throttling_without_header_uses_manifest_default():
    outcome = run_recorded(CannedTransport(429, body=load_recording("error_429")))
    assert outcome.status == "deferred"
    assert outcome.retry_after_s == MANIFEST.rate_limit["default_retry_after_s"]


def test_throttling_then_recovery_succeeds():
    document = run_ok(FlakyTransport(failures=2, error_status=429))
    assert len(document["objects"]) == len(FIXED_DIMENSIONS) + len(FIXED_METRICS)


def test_server_error_recovers_within_backoff():
    document = run_ok(FlakyTransport(failures=1, error_status=503))
    assert document["source_properties"]["properties"][0]["verified"] is True


def test_persistent_server_error_is_source_unavailable():
    outcome = run_recorded(CannedTransport(500))
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"
    assert outcome.error.retryable is True


def test_malformed_200_is_source_unavailable():
    outcome = run_recorded(CannedTransport(200, body=None))
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"


def test_missing_permission_field_is_source_unavailable():
    outcome = run_recorded(CannedTransport(200, body={"siteUrl": SITE}))
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"


# --- config / credential references (no transport injected) ---


def test_unset_credentials_env_is_config_error(monkeypatch):
    monkeypatch.delenv("CTXLAYER_GSC_TEST_UNSET", raising=False)
    outcome = run_job(
        Connector(manifest=MANIFEST, handlers={"metadata": GscMetadata(), "query": GscExecutor()}),
        Job.local(dict(CONFIG, credentials_env="CTXLAYER_GSC_TEST_UNSET")),
    )
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"


def test_config_without_site_url_rejected():
    config = {k: v for k, v in CONFIG.items() if k != "site_url"}
    outcome = run_recorded_config(config)
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"


def run_recorded_config(config: dict):
    transport = CannedTransport(200, body=load_recording("site_owner"))
    return run_job(make_connector(transport), Job.local(config))


# --- the task 1.4 exit criterion, live (env-gated) ---


@pytest.mark.gsc_live
@pytest.mark.skipif(
    not os.environ.get("CTXLAYER_GSC_LIVE"),
    reason="CTXLAYER_GSC_LIVE not set (needs CTXLAYER_GSC_SITE_URL "
    "+ GOOGLE_APPLICATION_CREDENTIALS)",
)
def test_live_property_and_fixed_schema_render_a_valid_snapshot():
    from connectors.gsc.connector import connector as live_connector

    config = {
        "system": "gsc",
        "mode": "api",
        "site_url": os.environ["CTXLAYER_GSC_SITE_URL"],
        "credentials_file": os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    }
    outcome = run_job(live_connector, Job.local(config))
    assert outcome.status == "succeeded", outcome.error
    document = outcome.snapshot.document
    errors, warnings = validate_snapshot(document, check_hashes=True)
    assert errors == [] and warnings == []
    entry = document["source_properties"]["properties"][0]
    assert entry["site_url"] == config["site_url"]
    assert entry["verified"] is True
    # the estate is the constant table regardless of transport
    assert objects_by_identity(document).keys() == objects_by_identity(run_ok()).keys()
