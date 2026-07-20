"""QueryExecutor conformance for the API-dialect connectors (GA4, GSC).

Fixture-driven against recorded response shapes — the same pattern the
metadata suites use. The live counterparts are env-gated
(`test_live_execute.py`).

Covers: the documented-operation allowlist, MT-8 refusal of an
undocumented dimension, CC-4 row cap over pagination, CC-6 (interactive
quota is terminal `guardrail`/`quota_exhausted`, never a defer), and
the schema_mismatch mapping for a source-rejected field.
"""

import pytest

from connectors.ga4.executor import GA4Executor
from connectors.gsc.executor import GscExecutor
from connectors.sdk import (
    ExecuteRequest,
    Guardrails,
    GuardrailViolation,
    Identity,
)
from connectors.sdk.runner import Job, run_job

IDENTITY = Identity(subject="oidc|a.demir@customer.example", session_id="s-1", intent="traffic")

GA4_CONFIG = {"system": "ga4", "mode": "api", "property_id": "313459823", "credentials_file": "unused"}
GSC_CONFIG = {"system": "gsc", "mode": "api", "site_url": "https://example-estate.com/", "credentials_file": "unused"}


class FakeTransport:
    """Records requests, replays queued responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def get(self, url, params=None):
        self.requests.append(("GET", url, params))
        return self._next()

    def post(self, url, json_body=None):
        self.requests.append(("POST", url, json_body))
        return self._next()

    def _next(self):
        if not self._responses:
            raise AssertionError("transport called more times than responses queued")
        return self._responses.pop(0)


def ga4_page(rows, *, dimensions=("country",), metrics=("activeUsers",), row_count=None):
    return (
        200,
        {},
        {
            "dimensionHeaders": [{"name": d} for d in dimensions],
            "metricHeaders": [{"name": m, "type": "TYPE_INTEGER"} for m in metrics],
            "rows": [
                {
                    "dimensionValues": [{"value": v} for v in row[: len(dimensions)]],
                    "metricValues": [{"value": v} for v in row[len(dimensions):]],
                }
                for row in rows
            ],
            "rowCount": row_count if row_count is not None else len(rows),
        },
    )


def gsc_page(rows):
    return (
        200,
        {},
        {
            "rows": [
                {"keys": r["keys"], "clicks": r["clicks"], "impressions": r["impressions"],
                 "ctr": r["ctr"], "position": r["position"]}
                for r in rows
            ]
        },
    )


def executor(cls, responses):
    transport = FakeTransport(responses)
    return cls(transport_factory=lambda config: transport, sleep=lambda _: None), transport


# --- GA4 --------------------------------------------------------------------


def test_ga4_runs_a_report():
    ex, transport = executor(GA4Executor, [ga4_page([["TR", "42"], ["DE", "17"]])])
    result = ex.execute(
        GA4_CONFIG,
        ExecuteRequest(dialect="api", operation="runReport",
                       body={"dimensions": [{"name": "country"}], "metrics": [{"name": "activeUsers"}],
                             "dateRanges": [{"startDate": "7daysAgo", "endDate": "today"}]}),
        Guardrails(row_cap=100),
        IDENTITY,
    )
    assert [c["name"] for c in result.columns] == ["country", "activeUsers"]
    assert result.rows == [["TR", "42"], ["DE", "17"]]
    assert result.truncated is False
    assert result.source["executed_on"] == "api"
    method, url, body = transport.requests[0]
    assert method == "POST" and url.endswith("properties/313459823:runReport")
    assert body["limit"] == 101  # cap + 1: truncation detected, not guessed


def test_ga4_undocumented_operation_refused_without_a_request():
    ex, transport = executor(GA4Executor, [])
    with pytest.raises(GuardrailViolation) as excinfo:
        ex.execute(
            GA4_CONFIG,
            ExecuteRequest(dialect="api", operation="runRealtimeReport", body={"metrics": [{"name": "x"}]}),
            Guardrails(),
            IDENTITY,
        )
    assert excinfo.value.capability_code == "schema_mismatch"
    assert transport.requests == []


def test_ga4_row_cap_truncates_across_pages():
    """CC-4 over pagination: the cap stops the paging, it does not trim
    afterwards."""
    ex, _ = executor(
        GA4Executor,
        [ga4_page([[str(i), str(i)] for i in range(3)], row_count=99)],
    )
    result = ex.execute(
        GA4_CONFIG,
        ExecuteRequest(dialect="api", operation="runReport",
                       body={"dimensions": [{"name": "country"}], "metrics": [{"name": "activeUsers"}]}),
        Guardrails(row_cap=2),
        IDENTITY,
    )
    assert len(result.rows) == 2
    assert result.truncated is True


def test_ga4_source_rejection_maps_to_schema_mismatch():
    """An undocumented dimension that somehow got past the gateway is
    refused by GA4; the caller gets the validate/execute race code, not
    an opaque 400."""
    ex, _ = executor(
        GA4Executor,
        [(400, {}, {"error": {"status": "INVALID_ARGUMENT", "message": "Did not recognize dimension"}})],
    )
    with pytest.raises(GuardrailViolation) as excinfo:
        ex.execute(
            GA4_CONFIG,
            ExecuteRequest(dialect="api", operation="runReport",
                           body={"dimensions": [{"name": "notADimension"}]}),
            Guardrails(),
            IDENTITY,
        )
    assert excinfo.value.capability_code == "schema_mismatch"


def test_ga4_interactive_quota_is_terminal_not_deferred():
    """CC-6/QE-4: the caller is blocked, so quota is a terminal
    guardrail error carrying retry-after — never a J-5 deferral."""
    from connectors.ga4.api import MANIFEST

    retries = MANIFEST.rate_limit["max_retries"]
    throttled = (429, {"Retry-After": "120"}, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    ex, _ = executor(GA4Executor, [throttled] * (retries + 1))

    from connectors.ga4.connector import connector

    job = Job(
        job_id="j-quota",
        config=GA4_CONFIG,
        type="execute",
        request={"dialect": "api", "operation": "runReport", "body": {"metrics": [{"name": "activeUsers"}]}},
        guardrails={"row_cap": 10, "timeout_s": 30},
        identity={"subject": "oidc|a"},
    )
    from connectors.sdk import Connector
    from connectors.ga4.connector import GA4Metadata

    outcome = run_job(
        Connector(manifest=MANIFEST, handlers={"metadata": GA4Metadata(), "query": ex}), job
    )
    assert outcome.status == "failed"  # not "deferred"
    assert outcome.error.code == "guardrail"
    assert outcome.error.detail["capability_code"] == "quota_exhausted"
    assert outcome.error.detail["retry_after_s"] == 120


# --- GSC --------------------------------------------------------------------


def test_gsc_runs_a_query():
    ex, transport = executor(
        GscExecutor,
        [gsc_page([{"keys": ["cv builder"], "clicks": 12, "impressions": 300, "ctr": 0.04, "position": 8.1}])],
    )
    result = ex.execute(
        GSC_CONFIG,
        ExecuteRequest(dialect="api", operation="searchAnalytics.query",
                       body={"startDate": "2026-06-01", "endDate": "2026-06-30", "dimensions": ["query"]}),
        Guardrails(row_cap=100),
        IDENTITY,
    )
    assert [c["name"] for c in result.columns] == ["query", "clicks", "impressions", "ctr", "position"]
    assert result.rows == [["cv builder", 12, 300, 0.04, 8.1]]
    assert result.truncated is False
    method, url, _ = transport.requests[0]
    assert method == "POST" and url.endswith("/searchAnalytics/query")


def test_gsc_undocumented_dimension_refused_locally():
    """MT-8 at the executor: GSC's vocabulary is a compiled constant, so
    the refusal happens before any request is made."""
    ex, transport = executor(GscExecutor, [])
    with pytest.raises(GuardrailViolation) as excinfo:
        ex.execute(
            GSC_CONFIG,
            ExecuteRequest(dialect="api", operation="searchAnalytics.query",
                           body={"startDate": "2026-06-01", "endDate": "2026-06-30",
                                 "dimensions": ["query", "browser"]}),
            Guardrails(),
            IDENTITY,
        )
    assert excinfo.value.capability_code == "schema_mismatch"
    assert excinfo.value.detail["undocumented_dimensions"] == ["browser"]
    assert transport.requests == []


def test_gsc_row_cap_truncates():
    ex, _ = executor(
        GscExecutor,
        [gsc_page([
            {"keys": [f"q{i}"], "clicks": i, "impressions": i * 10, "ctr": 0.1, "position": 1.0}
            for i in range(5)
        ])],
    )
    result = ex.execute(
        GSC_CONFIG,
        ExecuteRequest(dialect="api", operation="searchAnalytics.query",
                       body={"startDate": "2026-06-01", "endDate": "2026-06-30", "dimensions": ["query"]}),
        Guardrails(row_cap=3),
        IDENTITY,
    )
    assert len(result.rows) == 3
    assert result.truncated is True


def test_gsc_requires_a_date_range():
    ex, _ = executor(GscExecutor, [])
    with pytest.raises(GuardrailViolation) as excinfo:
        ex.execute(
            GSC_CONFIG,
            ExecuteRequest(dialect="api", operation="searchAnalytics.query", body={"dimensions": ["query"]}),
            Guardrails(),
            IDENTITY,
        )
    assert excinfo.value.capability_code == "syntax_error"


# --- shared: guardrail independence (CC-3 for the API dialect) --------------


def test_api_executors_cap_rows_with_guardrails_absent_from_payload():
    """CC-3's API-side analogue: no guardrails in the payload still
    yields the conservative default cap, not an unbounded pull."""
    ex, transport = executor(
        GscExecutor,
        [gsc_page([
            {"keys": [f"q{i}"], "clicks": 1, "impressions": 1, "ctr": 0.1, "position": 1.0}
            for i in range(10)
        ])],
    )
    from connectors.gsc.api import MANIFEST as GSC_MANIFEST
    from connectors.sdk import Connector
    from connectors.gsc.connector import GscMetadata

    job = Job(
        job_id="j-nogr",
        config=GSC_CONFIG,
        type="execute",
        request={"dialect": "api", "operation": "searchAnalytics.query",
                 "body": {"startDate": "2026-06-01", "endDate": "2026-06-30", "dimensions": ["query"]}},
        guardrails=None,
        identity={"subject": "oidc|a"},
    )
    outcome = run_job(
        Connector(manifest=GSC_MANIFEST, handlers={"metadata": GscMetadata(), "query": ex}), job
    )
    assert outcome.status == "succeeded"
    # Defaulted cap is 1000, so the request asked for 1001, not "everything".
    assert transport.requests[0][2]["rowLimit"] == 1001
