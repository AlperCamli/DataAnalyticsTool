"""GA4 connector on recorded API responses, plus the env-gated live pull.

Connector-level renderings of the conformance suite (deliverable 5):
C-1/C-4 via the emission gate, C-2 (byte-identical reruns on
recordings), C-5/S-2 (description-only change → metadata-only diff,
no hash moves), C-6 (new custom dimension → exactly one added), J-5
(persistent throttling → deferral, never failure), MP-1/CC-2 (any
other API failure → taxonomy failure, nothing emitted), D-23 (torn
read across surfaces → source_unavailable).

The recordings (tests/data/ga4/) are wire-shaped responses for one
property, covering all three surfaces with two custom dimensions
(EVENT + USER scope, served across two pages to exercise pagination),
a plain custom metric, a calculated custom metric, and two key events
(one standard, one custom).
"""

import copy
import json
import os
import random
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from connectors.ga4.connector import MANIFEST, GA4Metadata
from connectors.ga4.executor import GA4Executor
from connectors.ga4.connector import connector as live_connector
from connectors.sdk import Connector, Job, run_job
from snapshot.canonical import canonical_body_bytes
from snapshot.diff import diff_snapshots
from snapshot.validate import validate_snapshot

RECORDINGS = Path(__file__).resolve().parent / "data" / "ga4"

CONFIG = {
    "system": "ga4",
    "mode": "api",
    "property_id": "313459823",
    "credentials_env": "GA4_SA_JSON",  # never resolved: tests inject the transport
}


def load_recording(name: str) -> dict:
    return json.loads((RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))


def recorded_responses() -> dict:
    """Route key → response. List endpoints key on (segment, pageToken)."""
    return {
        "property": load_recording("property"),
        "metadata": load_recording("metadata"),
        ("customDimensions", None): load_recording("custom_dimensions.page1"),
        ("customDimensions", "page-2"): load_recording("custom_dimensions.page2"),
        ("customMetrics", None): load_recording("custom_metrics"),
        ("calculatedMetrics", None): load_recording("calculated_metrics"),
        ("keyEvents", None): load_recording("key_events"),
    }


class RecordedTransport:
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, params: dict | None = None):
        segment = urlsplit(url).path.rsplit("/", 1)[-1]
        self.calls.append(segment)
        key = "property" if segment.isdigit() else segment
        if key not in ("property", "metadata"):
            key = (segment, (params or {}).get("pageToken"))
        return 200, {}, copy.deepcopy(self.responses[key])


class CannedTransport:
    """Always returns the same canned (status, headers, body)."""

    def __init__(self, status: int, headers: dict | None = None, body: dict | None = None):
        self.status, self.headers, self.body = status, headers or {}, body
        self.calls = 0

    def get(self, url: str, params: dict | None = None):
        self.calls += 1
        return self.status, dict(self.headers), copy.deepcopy(self.body)


class FlakyTransport(RecordedTransport):
    """Fails the first `failures` calls with a canned error, then recovers."""

    def __init__(self, responses: dict, failures: int, status: int):
        super().__init__(responses)
        self.remaining, self.error_status = failures, status

    def get(self, url: str, params: dict | None = None):
        if self.remaining > 0:
            self.remaining -= 1
            return self.error_status, {}, None
        return super().get(url, params)


def make_connector(transport) -> Connector:
    provider = GA4Metadata(
        transport_factory=lambda config: transport,
        sleep=lambda seconds: None,  # tests never really sleep
        rng=random.Random(7),
    )
    return Connector(manifest=MANIFEST, handlers={"metadata": provider, "query": GA4Executor()})


def run_recorded(responses: dict | None = None, transport=None, **kwargs):
    transport = transport or RecordedTransport(responses or recorded_responses())
    return run_job(make_connector(transport), Job.local(dict(CONFIG)), **kwargs)


def objects_by_name(document: dict) -> dict:
    return {(o["kind"], o["name"]): o for o in document["objects"]}


# --- success path: all three surfaces mapped (C-1/C-4 via the gate) ---


def test_recorded_pull_emits_valid_snapshot():
    outcome = run_recorded()
    assert outcome.status == "succeeded", outcome.error
    doc = outcome.snapshot.document
    assert validate_snapshot(doc, check_hashes=True) == ([], [])
    assert doc["system_class"] == "api"
    assert doc["source_mode"] == "api"  # MP-1
    assert doc["connector"] == {"name": "ga4", "version": MANIFEST.version}
    assert doc["source_properties"] == {  # MP-2 / D-27, fixture-identical keys
        "property_id": "properties/313459823",
        "display_name": "Acme Store — Web",
        "time_zone": "Europe/Istanbul",
        "currency_code": "TRY",
    }
    kinds = [o["kind"] for o in doc["objects"]]
    assert kinds.count("api_dimension") == 6
    assert kinds.count("api_metric") == 5
    assert kinds.count("api_event") == 2


def test_standard_dimension_mapping():
    doc = run_recorded().snapshot.document
    country = objects_by_name(doc)[("api_dimension", "country")]
    assert country["schema"] == "standard"
    assert country["description"] == "The country from which the user activity originated."
    assert country["stats"] == {"data_type": "string"}  # D-24
    assert country["columns"] == [] and country["keys"] == {}
    # absent description → null; deprecatedApiNames dropped at the boundary (D-26)
    unified = objects_by_name(doc)[("api_dimension", "unifiedScreenName")]
    assert unified["description"] is None
    assert unified["stats"] == {"data_type": "string"}


def test_custom_dimension_mapping_scope_rides_the_name():
    doc = run_recorded().snapshot.document
    crm = objects_by_name(doc)[("api_dimension", "customUser:crm_id")]
    assert crm["schema"] == "custom"
    assert crm["description"] == "CRM identifier synced from the sales pipeline."
    # D-23: no stats.scope for dimensions — USER scope is the customUser: prefix
    assert crm["stats"] == {"data_type": "string"}
    plan = objects_by_name(doc)[("api_dimension", "customEvent:plan_tier")]
    assert plan["schema"] == "custom"  # crm_id came from page 2: pagination works


def test_metric_mapping_standard_custom_calculated():
    doc = run_recorded().snapshot.document
    by_name = objects_by_name(doc)
    assert by_name[("api_metric", "totalRevenue")]["stats"] == {"data_type": "TYPE_CURRENCY"}
    tickets = by_name[("api_metric", "customEvent:support_tickets")]
    assert tickets["schema"] == "custom"
    assert tickets["stats"] == {"data_type": "TYPE_INTEGER", "scope": "EVENT"}
    calc = by_name[("api_metric", "calcMetric:revenue_per_user")]
    assert calc["schema"] == "custom"
    assert calc["stats"] == {
        "data_type": "TYPE_CURRENCY",
        "formula": "totalRevenue/activeUsers",  # verbatim Admin formula, no scope
    }


def test_key_event_mapping():
    doc = run_recorded().snapshot.document
    by_name = objects_by_name(doc)
    purchase = by_name[("api_event", "purchase")]
    assert purchase["schema"] == "standard"  # KeyEvent.custom=false → origin namespace (D-25)
    assert purchase["stats"] == {"is_key_event": True}
    assert purchase["description"] is None  # key events carry no description
    assert purchase["columns"] == []  # parameters not introspectable
    assert by_name[("api_event", "sign_up_completed")]["schema"] == "custom"


# --- C-2: byte-identical reruns on unchanged recordings ---


def test_c2_reruns_byte_identical():
    first, second = run_recorded(), run_recorded()
    assert canonical_body_bytes(first.snapshot.document) == canonical_body_bytes(
        second.snapshot.document
    )
    pinned = "2026-07-12T00:00:00Z"
    a = run_recorded(captured_at=pinned)
    b = run_recorded(captured_at=pinned)
    assert a.snapshot.serialized == b.snapshot.serialized


# --- S-2 / C-5: description-only change → metadata-only, no hash moves ---


def test_s2_description_change_is_metadata_only():
    baseline = run_recorded().snapshot.document
    edited = recorded_responses()
    dim = next(d for d in edited["metadata"]["dimensions"] if d["apiName"] == "country")
    dim["description"] = "The country of the user, derived from IP geolocation."
    changed = run_recorded(edited).snapshot.document

    old_hashes = {(o["kind"], o["name"]): o["schema_hash"] for o in baseline["objects"]}
    new_hashes = {(o["kind"], o["name"]): o["schema_hash"] for o in changed["objects"]}
    assert old_hashes == new_hashes  # every schema_hash unchanged

    diff = diff_snapshots(baseline, changed, verify_hashes=True)
    assert not diff.added and not diff.removed and not diff.changed_structural
    assert [d.identity for d in diff.changed_metadata_only] == [
        ("api_dimension", "standard", "country")
    ]


# --- structural counterpart / C-6: new custom dimension → exactly one added ---


def test_new_custom_dimension_is_exactly_one_added():
    baseline = run_recorded().snapshot.document
    grown = recorded_responses()
    grown["metadata"]["dimensions"].append(
        {
            "apiName": "customEvent:checkout_step",
            "uiName": "Checkout step",
            "description": "Step of the checkout funnel.",
            "customDefinition": True,
            "category": "Custom",
        }
    )
    grown[("customDimensions", "page-2")]["customDimensions"].append(
        {
            "name": "properties/313459823/customDimensions/6001",
            "parameterName": "checkout_step",
            "displayName": "Checkout step",
            "description": "Step of the checkout funnel.",
            "scope": "EVENT",
        }
    )
    changed = run_recorded(grown).snapshot.document

    diff = diff_snapshots(baseline, changed, verify_hashes=True)
    assert [d.identity for d in diff.added] == [
        ("api_dimension", "custom", "customEvent:checkout_step")
    ]
    assert not diff.removed and not diff.changed_structural and not diff.changed_metadata_only


# --- quota: J-5 deferral, never a failure ---


def test_persistent_throttle_defers_with_retry_after_header():
    transport = CannedTransport(
        429, headers={"Retry-After": "1800"}, body={"error": {"status": "RESOURCE_EXHAUSTED"}}
    )
    outcome = run_recorded(transport=transport)
    assert outcome.status == "deferred"
    assert outcome.retry_after_s == 1800
    assert outcome.error.code == "quota"
    assert outcome.snapshot is None
    # one initial call + the manifest's max_retries backoff attempts
    assert transport.calls == 1 + MANIFEST.rate_limit["max_retries"]


def test_throttle_without_header_uses_manifest_default():
    transport = CannedTransport(403, body={"error": {"status": "RESOURCE_EXHAUSTED"}})
    outcome = run_recorded(transport=transport)
    assert outcome.status == "deferred"
    assert outcome.retry_after_s == MANIFEST.rate_limit["default_retry_after_s"]


def test_transient_throttle_recovers_within_backoff():
    outcome = run_recorded(transport=FlakyTransport(recorded_responses(), failures=2, status=429))
    assert outcome.status == "succeeded"


# --- every other API failure: taxonomy, no fallback, nothing emitted (MP-1/CC-2) ---


def test_server_error_fails_source_unavailable_after_backoff():
    transport = CannedTransport(503)
    outcome = run_recorded(transport=transport)
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"
    assert outcome.error.retryable is True
    assert outcome.snapshot is None
    assert transport.calls == 1 + MANIFEST.rate_limit["max_retries"]


def test_permission_denied_fails_auth_error():
    outcome = run_recorded(
        transport=CannedTransport(403, body={"error": {"status": "PERMISSION_DENIED"}})
    )
    assert outcome.status == "failed"
    assert outcome.error.code == "auth_error"
    assert outcome.error.retryable is False
    assert outcome.snapshot is None


def test_unknown_property_fails_config_error():
    outcome = run_recorded(transport=CannedTransport(404, body={"error": {"status": "NOT_FOUND"}}))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.snapshot is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r[("customDimensions", "page-2")].update({"customDimensions": []}),
        lambda r: r["metadata"]["dimensions"].pop(5),  # customUser:crm_id
        lambda r: r[("calculatedMetrics", None)].update({"calculatedMetrics": []}),
    ],
    ids=["admin-missing-dimension", "metadata-missing-dimension", "admin-missing-calc"],
)
def test_torn_read_between_surfaces_fails_retryable(mutate):
    responses = recorded_responses()
    mutate(responses)
    outcome = run_recorded(responses)
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"
    assert outcome.error.retryable is True
    assert "disagree" in outcome.error.message
    assert outcome.snapshot is None


# --- live pull (task 1.3 exit criterion), gated behind an env flag ---

LIVE_GATE = "CTXLAYER_GA4_LIVE"


@pytest.mark.ga4_live
@pytest.mark.skipif(
    not os.environ.get(LIVE_GATE),
    reason=f"set {LIVE_GATE}=1, CTXLAYER_GA4_PROPERTY_ID and "
    "GOOGLE_APPLICATION_CREDENTIALS to run the live GA4 pull",
)
def test_live_pull_produces_valid_objects_including_custom_definitions():
    property_id = os.environ["CTXLAYER_GA4_PROPERTY_ID"]
    config = {
        "system": "ga4",
        "mode": "api",
        "property_id": property_id,
        "credentials_file": os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
    }
    outcome = run_job(live_connector, Job.local(config))
    assert outcome.status == "succeeded", outcome.error
    doc = outcome.snapshot.document
    assert validate_snapshot(doc, check_hashes=True) == ([], [])
    kinds = {o["kind"] for o in doc["objects"]}
    assert {"api_dimension", "api_metric", "api_event"} <= kinds
    assert any(o["schema"] == "custom" for o in doc["objects"])  # incl. custom definitions
    assert doc["source_properties"]["property_id"] == f"properties/{property_id}"
