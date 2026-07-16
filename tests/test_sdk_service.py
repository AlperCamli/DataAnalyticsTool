"""Runner daemon semantics (connectors/sdk/service.py) with a scripted
client — the runner-side half of the conformance table: outcome→wire
mapping (§6.4–§6.6), JC-6 (422 final), JC-7 (cancel within one
heartbeat interval), JC-8 (credential injection leaves no secret in any
outgoing message), and lease-loss abandonment (J-7).
"""

import json
import os
import time

import pytest

from connectors.sdk import IntrospectionResult, SourceUnavailable
from connectors.sdk.errors import QuotaExceeded
from connectors.sdk.protocol import DeliveryRejected, LeaseLost
from connectors.sdk.service import (
    CREDENTIAL_CONFIG_KEYS,
    Runner,
    RunnerConfig,
    RunnerConfigError,
    load_runner_config,
    scrub_secrets,
)
from connectors.sdk.vault import EnvResolver
from connectors.static_demo.connector import connector as demo_connector
from snapshot.accept import accept
from tests.conftest import make_connector


class FakeClient:
    """Records wire calls; heartbeat responses follow a script."""

    def __init__(self, heartbeat_script=None):
        self.calls: list[tuple] = []
        self.heartbeat_script = list(heartbeat_script or [])
        self.complete_error: Exception | None = None
        self.heartbeat_error: Exception | None = None
        self.start_response: dict = {"status": "running", "cancel_requested": False}

    def start(self, job_id, lease_token):
        self.calls.append(("start", job_id, lease_token))
        return dict(self.start_response)

    def heartbeat(self, job_id, lease_token, progress=None):
        self.calls.append(("heartbeat", job_id, lease_token))
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        if self.heartbeat_script:
            return self.heartbeat_script.pop(0)
        return {"lease": {"token": lease_token}, "cancel_requested": False}

    def complete_snapshot(self, job_id, lease_token, serialized):
        self.calls.append(("complete", job_id, lease_token, serialized))
        if self.complete_error is not None:
            raise self.complete_error
        return {"status": "succeeded"}

    def fail(self, job_id, lease_token, error):
        self.calls.append(("fail", job_id, lease_token, error))
        return {"status": "dead_lettered"}

    def defer(self, job_id, lease_token, retry_after_s, reason):
        self.calls.append(("defer", job_id, lease_token, retry_after_s, reason))
        return {"status": "deferred"}

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def make_runner(client, connectors, resolver=None, interval=0.05) -> Runner:
    config = RunnerConfig(
        core_url="http://stub", token="t", runner_id="r-test",
        connector_specs=("unused:unused",), heartbeat_interval_s=interval,
    )
    return Runner(
        config=config, client=client, connectors=connectors,
        resolver=resolver or EnvResolver({}),
    )


def job_record(*, connector="static-demo", system="demo", config=None,
               credentials=None, job_type="snapshot", ttl_s=1.0):
    return {
        "job_id": "01TESTJOB",
        "type": job_type,
        "class": "batch",
        "system": system,
        "connector": {"name": connector, "version_constraint": "*"},
        "payload": {
            "config": config or {"system": system, "mode": "ddl-file"},
            "credentials": credentials or [],
        },
        "lease": {"token": "L1", "ttl_s": ttl_s},
    }


# --- outcome → wire mapping ---


def test_success_delivers_valid_canonical_snapshot():
    client = FakeClient()
    make_runner(client, {"static-demo": demo_connector}).execute(job_record())
    assert [c[0] for c in client.calls if c[0] in ("start", "complete")] == [
        "start", "complete",
    ]
    (_, _, _, serialized) = client.named("complete")[0]
    verdict, _ = accept(json.loads(serialized))
    assert verdict["valid"] is True
    assert verdict["system"] == "demo"


def test_connector_failure_maps_to_fail_call():
    client = FakeClient()
    runner = make_runner(client, {"static-demo": demo_connector})
    runner.execute(job_record(config={
        "system": "demo", "mode": "ddl-file", "inject_failure": "source_unavailable",
    }))
    (_, _, _, error) = client.named("fail")[0]
    assert error["code"] == "source_unavailable"
    assert error["retryable"] is True
    assert client.named("complete") == []


def test_quota_maps_to_defer_call():
    client = FakeClient()
    runner = make_runner(client, {"static-demo": demo_connector})
    runner.execute(job_record(config={
        "system": "demo", "mode": "ddl-file", "inject_failure": "quota",
    }))
    (_, _, _, retry_after_s, reason) = client.named("defer")[0]
    assert retry_after_s == 3600
    assert reason["code"] == "quota"
    assert client.named("fail") == []


def test_delivery_rejected_is_final():
    """JC-6: after a 422 the runner neither retries nor calls fail."""
    client = FakeClient()
    client.complete_error = DeliveryRejected("complete: rejected", errors=["bad hash"])
    make_runner(client, {"static-demo": demo_connector}).execute(job_record())
    assert len(client.named("complete")) == 1
    assert client.named("fail") == []


def test_unknown_connector_or_type_fails_config_error():
    client = FakeClient()
    runner = make_runner(client, {"static-demo": demo_connector})
    runner.execute(job_record(job_type="usage"))
    assert client.named("fail")[0][3]["code"] == "config_error"


# --- cancellation (JC-7) ---


def test_cancel_requested_stops_within_one_interval(tmp_path):
    def sleepy(config):
        time.sleep(5)
        raise AssertionError("worker outcome must be discarded")

    connector = make_connector(tmp_path, sleepy)
    client = FakeClient(heartbeat_script=[
        {"lease": {"token": "L1"}, "cancel_requested": True},
    ])
    runner = make_runner(client, {"testconn": connector}, interval=0.05)
    started = time.monotonic()
    runner.execute(job_record(connector="testconn", system="t1"))
    elapsed = time.monotonic() - started
    assert elapsed < 2.0  # stopped without waiting out the 5 s worker
    (_, _, _, error) = client.named("fail")[0]
    assert error["code"] == "cancelled"
    assert client.named("complete") == []


def test_cancel_already_requested_at_start(tmp_path):
    client = FakeClient()
    client.start_response = {"status": "running", "cancel_requested": True}
    runner = make_runner(client, {"static-demo": demo_connector})
    runner.execute(job_record())
    assert client.named("fail")[0][3]["code"] == "cancelled"
    assert client.named("complete") == []


# --- lease loss (J-7 abandonment) ---


def test_lease_lost_on_heartbeat_abandons_work(tmp_path):
    def sleepy(config):
        time.sleep(5)
        return IntrospectionResult(system_class="sql", objects=[])

    connector = make_connector(tmp_path, sleepy)
    client = FakeClient()
    client.heartbeat_error = LeaseLost("heartbeat: lease lost (409)")
    runner = make_runner(client, {"testconn": connector}, interval=0.05)
    started = time.monotonic()
    runner.execute(job_record(connector="testconn", system="t1"))
    assert time.monotonic() - started < 2.0
    assert client.named("complete") == []
    assert client.named("fail") == []
    assert client.named("defer") == []


def test_lease_lost_at_start_abandons(tmp_path):
    client = FakeClient()

    def raise_lost(job_id, lease_token):
        client.calls.append(("start", job_id, lease_token))
        raise LeaseLost("start: lease lost (409)")

    client.start = raise_lost
    make_runner(client, {"static-demo": demo_connector}).execute(job_record())
    assert client.named("complete") == []
    assert client.named("fail") == []


# --- credentials (J-4 / JC-8) ---


def test_credential_injection_and_cleanup(tmp_path):
    secret = "unit-test-canary-zzzz"
    seen: dict = {}

    def check(config):
        var = config["dsn_env"]
        seen["var"] = var
        seen["value"] = os.environ.get(var)
        return IntrospectionResult(system_class="sql", objects=[])

    connector = make_connector(tmp_path, check)
    client = FakeClient()
    runner = make_runner(
        client, {"testconn": connector}, resolver=EnvResolver({"MY_DSN": secret}),
    )
    runner.execute(job_record(
        connector="testconn", system="t1",
        credentials=[{"ref": "env://MY_DSN", "key": "dsn"}],
    ))
    assert seen["value"] == secret
    assert seen["var"] not in os.environ  # cleaned up after the job
    # JC-8: the secret never appears in any outgoing message.
    assert secret not in json.dumps([list(map(str, c)) for c in client.calls])


def test_vault_failure_is_auth_error_with_stage():
    client = FakeClient()
    runner = make_runner(client, {"static-demo": demo_connector})
    runner.execute(job_record(
        credentials=[{"ref": "env://ABSENT", "key": "dsn"}],
    ))
    (_, _, _, error) = client.named("fail")[0]
    assert error["code"] == "auth_error"
    assert error["detail"] == {"stage": "vault"}


def test_unknown_credential_key_rejected():
    client = FakeClient()
    runner = make_runner(
        client, {"static-demo": demo_connector}, resolver=EnvResolver({"X": "v"}),
    )
    runner.execute(job_record(credentials=[{"ref": "env://X", "key": "oauth_blob"}]))
    assert client.named("fail")[0][3]["code"] == "auth_error"


def test_error_scrubbing_redacts_resolved_secrets(tmp_path):
    secret = "unit-test-canary-zzzz"

    def leaky(config):
        raise SourceUnavailable(f"connection refused for {secret}")

    connector = make_connector(tmp_path, leaky)
    client = FakeClient()
    runner = make_runner(
        client, {"testconn": connector}, resolver=EnvResolver({"DSN": secret}),
    )
    runner.execute(job_record(
        connector="testconn", system="t1",
        credentials=[{"ref": "env://DSN", "key": "dsn"}],
    ))
    (_, _, _, error) = client.named("fail")[0]
    assert secret not in json.dumps(error)
    assert "[REDACTED]" in error["message"]


def test_scrub_secrets_handles_nested_detail():
    scrubbed = scrub_secrets(
        {"detail": {"dsn": "postgres://u:hunter2@h/db"}, "message": "hunter2 bad"},
        ["hunter2"],
    )
    assert json.dumps(scrubbed).count("hunter2") == 0


# --- declaration + config loading ---


def test_declared_connectors_carry_types():
    runner = make_runner(FakeClient(), {"static-demo": demo_connector})
    assert runner.declared_connectors() == [
        {"name": "static-demo", "version": "0.1.0", "types": ["snapshot"]},
    ]


def test_credential_key_map_covers_shipped_connectors():
    assert CREDENTIAL_CONFIG_KEYS == {
        "dsn": "dsn_env",
        "service_account": "credentials_env",
    }


def test_load_runner_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CL_TOKEN_TEST", "tok")
    config_file = tmp_path / "runner.yaml"
    config_file.write_text(
        "core_url: http://core:8100\n"
        "token_env: CL_TOKEN_TEST\n"
        "connectors:\n"
        "  - connectors.static_demo.connector:connector\n"
        "resolver: { kind: env-file, path: /secrets/cl.env }\n",
        encoding="utf-8",
    )
    config = load_runner_config(config_file)
    assert config.token == "tok"
    assert config.resolver_kind == "env-file"
    assert config.classes == ("batch",)


def test_load_runner_config_rejects_missing_token(tmp_path):
    config_file = tmp_path / "runner.yaml"
    config_file.write_text(
        "core_url: http://core:8100\nconnectors: [a:b]\n", encoding="utf-8",
    )
    with pytest.raises(RunnerConfigError):
        load_runner_config(config_file)
