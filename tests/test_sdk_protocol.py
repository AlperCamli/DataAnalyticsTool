"""Wire-client behavior (connectors/sdk/protocol.py) against a stub core.

Covers the header contract (bearer + protocol version on every call),
the §6.4 canonical-bytes splice, the 409/422 mappings the runner's
correctness depends on (JC-3 stale-lease, JC-6 no-retry-on-422), and
the transient-retry policy for terminal calls.
"""

import json
import threading
import time

import requests
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from connectors.sdk.protocol import (
    DeliveryRejected,
    JobApiClient,
    LeaseLost,
    ProtocolError,
)


class StubCore:
    """Scripted responses per (method, path); records every request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.scripts: dict[str, list[tuple[int, dict | None]]] = {}
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                stub.requests.append({
                    "path": self.path,
                    "headers": dict(self.headers),
                    "body": body,
                })
                queue = stub.scripts.get(self.path, [])
                status, payload = queue.pop(0) if queue else (200, {})
                data = b"" if payload is None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def stub():
    core = StubCore()
    yield core
    core.close()


def make_client(stub, **kwargs) -> JobApiClient:
    kwargs.setdefault("deliver_backoff_s", 0.01)
    return JobApiClient(stub.url, "runner-token-1", **kwargs)


def test_headers_on_every_call(stub):
    stub.scripts["/v1/jobs/claim"] = [(204, None)]
    make_client(stub).claim(runner_id="r1", connectors=[], classes=["batch"], wait_s=0)
    headers = stub.requests[0]["headers"]
    assert headers["Authorization"] == "Bearer runner-token-1"
    assert headers["X-CL-Protocol-Version"] == "1"
    assert headers["Content-Type"] == "application/json"


def test_claim_204_is_none_200_is_job(stub):
    stub.scripts["/v1/jobs/claim"] = [
        (204, None),
        (200, {"job_id": "J1", "lease": {"token": "L1"}}),
    ]
    client = make_client(stub)
    assert client.claim(runner_id="r1", connectors=[], classes=["batch"], wait_s=0) is None
    job = client.claim(
        runner_id="r1",
        connectors=[{"name": "static-demo", "version": "0.1.0", "types": ["snapshot"]}],
        classes=["batch"],
        wait_s=0,
    )
    assert job["job_id"] == "J1"
    sent = json.loads(stub.requests[1]["body"])
    assert sent["runner_id"] == "r1"
    assert sent["connectors"][0]["types"] == ["snapshot"]


def test_complete_splices_canonical_bytes_verbatim(stub):
    serialized = b'{"objects":[],"schema_hash":"x","system":"demo"}\n'
    stub.scripts["/v1/jobs/J1/complete"] = [(200, {"status": "succeeded"})]
    make_client(stub).complete_snapshot("J1", "L1", serialized)
    body = stub.requests[0]["body"]
    assert body == b'{"lease_token":"L1","result":' + serialized.strip() + b"}"


def test_409_raises_lease_lost(stub):
    stub.scripts["/v1/jobs/J1/heartbeat"] = [(409, {"error": "lease_lost"})]
    with pytest.raises(LeaseLost):
        make_client(stub).heartbeat("J1", "stale")


def test_422_raises_delivery_rejected_and_never_retries(stub):
    stub.scripts["/v1/jobs/J1/complete"] = [
        (422, {"status": "dead_lettered", "errors": ["schema_hash mismatch"]}),
        (200, {"status": "succeeded"}),  # must never be reached
    ]
    with pytest.raises(DeliveryRejected) as excinfo:
        make_client(stub).complete_snapshot("J1", "L1", b"{}")
    assert excinfo.value.errors == ["schema_hash mismatch"]
    assert len(stub.requests) == 1  # JC-6: 422 is final


def test_5xx_on_terminal_call_retries_then_succeeds(stub):
    stub.scripts["/v1/jobs/J1/fail"] = [
        (503, {"error": "unavailable"}),
        (200, {"status": "requeued"}),
    ]
    result = make_client(stub).fail(
        "J1", "L1", {"code": "internal", "message": "x", "retryable": True}
    )
    assert result["status"] == "requeued"
    assert len(stub.requests) == 2


def test_unexpected_status_is_protocol_error(stub):
    stub.scripts["/v1/jobs/J1/start"] = [(418, {})]
    with pytest.raises(ProtocolError):
        make_client(stub).start("J1", "L1")


# --- transport resilience (found live: a core restart killed the runner) ---


class _DeadTransport:
    """A session whose connection is severed mid-call, as happens when the
    core restarts under a long-poll claim."""

    def __init__(self, exc=None):
        self.calls = 0
        self._exc = exc or requests.exceptions.ConnectionError(
            "('Connection aborted.', RemoteDisconnected('Remote end closed connection'))"
        )

    def post(self, *args, **kwargs):
        self.calls += 1
        raise self._exc


@pytest.mark.parametrize("call", ["claim", "start", "heartbeat"])
def test_transport_failure_surfaces_as_protocol_error_not_a_crash(call):
    """The runner's loop only knows ProtocolError. A raw
    requests.ConnectionError escaping `claim` takes the process down —
    which is exactly what happened when the core was restarted during the
    M2 demo: every runner died and jobs sat queued until the sync run
    timed out. Transport failures must arrive as ProtocolError so
    `run_forever` backs off and reconnects (J-2)."""
    transport = _DeadTransport()
    client = JobApiClient("http://core", "tok", session=transport)

    with pytest.raises(ProtocolError) as excinfo:
        if call == "claim":
            client.claim(runner_id="r", connectors=[], classes=["batch"], wait_s=1)
        elif call == "start":
            client.start("j1", "lease")
        else:
            client.heartbeat("j1", "lease")

    assert call in str(excinfo.value)
    assert "transport failure" in str(excinfo.value)
    # Not a requests exception leaking through.
    assert not isinstance(excinfo.value, requests.RequestException)


def test_runner_loop_survives_a_core_restart_and_keeps_claiming():
    """End of the same story: the loop must back off and carry on."""
    from connectors.sdk.service import Runner, RunnerConfig

    class FlakyClient:
        def __init__(self):
            self.attempts = 0

        def claim(self, **kwargs):
            self.attempts += 1
            if self.attempts <= 3:
                raise ProtocolError("claim: transport failure (connection aborted)")
            return None  # nothing to do; loop continues

    client = FlakyClient()
    config = RunnerConfig(
        core_url="http://core", token="t", runner_id="r1",
        connector_specs=(), classes=("batch",), claim_backoff_s=0.0,
    )
    runner = Runner(config=config, client=client, connectors={}, resolver=object())
    # max_jobs stops the loop; claim returning None never executes a job, so
    # run it in a thread and stop once it has pushed past the failures.
    import threading
    t = threading.Thread(target=lambda: runner.run_forever(max_jobs=0), daemon=True)
    t.start()
    deadline = time.time() + 5
    while client.attempts <= 4 and time.time() < deadline:
        time.sleep(0.02)
    assert client.attempts > 3, "runner stopped claiming after transport failures"
