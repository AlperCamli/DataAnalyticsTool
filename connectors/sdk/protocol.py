"""Job-protocol HTTP client (job spec §6) — the runner side of the wire.

Speaks exactly the six calls a runner may make: claim, start, heartbeat,
complete, fail, defer. All requests carry the per-runner bearer token
(J-8) and `X-CL-Protocol-Version: 1`; unknown response fields are
ignored (§6 additive evolution — callers read only what they need).

Snapshot completes splice the SDK's canonical serialization into the
request body verbatim (`complete_snapshot`), so the canonical bytes
transit the wire without a Python→JSON round-trip; paired with the
core's Python-side re-canonicalization this keeps accepted snapshots
byte-identical to local CLI harness output (C-2 across the transport).

Error mapping: `409` → `LeaseLost` (abandon the work, J-7 makes
re-execution safe); `422` on complete → `DeliveryRejected` (final, never
retried — JC-6); transient transport/5xx errors retry with a short
backoff for the terminal calls, since losing a deliverable outcome to a
network blip would waste a whole attempt.
"""

import json
import logging
import time

import requests

PROTOCOL_VERSION = "1"
logger = logging.getLogger("connectors.sdk.protocol")


class ProtocolError(Exception):
    """Unexpected core response (bad status, malformed body)."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class LeaseLost(ProtocolError):
    """409 — a stale lease token; abandon the work (§5)."""


class DeliveryRejected(ProtocolError):
    """422 on complete — J-6 validation failed; final, never retried."""

    def __init__(self, message: str, *, errors: list[str] | None = None):
        super().__init__(message, status=422)
        self.errors = errors or []


class JobApiClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout_s: float = 30.0,
        deliver_retries: int = 3,
        deliver_backoff_s: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-CL-Protocol-Version": PROTOCOL_VERSION,
            "Content-Type": "application/json",
        }
        self.timeout_s = timeout_s
        self.deliver_retries = deliver_retries
        self.deliver_backoff_s = deliver_backoff_s

    # -- plumbing ---------------------------------------------------------

    def _send(self, path: str, body: bytes, *, timeout_s: float) -> requests.Response:
        """Raw POST. Transport exceptions propagate — only `_deliver`,
        which has its own retry ladder, calls this directly."""
        return self._session.post(
            f"{self.base_url}{path}", data=body, headers=self._headers, timeout=timeout_s
        )

    def _post(self, path: str, body: bytes, *, timeout_s: float, call: str = "request") -> requests.Response:
        """POST with transport failures mapped into the protocol taxonomy.

        Without this, a core restart kills every runner: the long-poll
        claim is cut mid-flight, `requests` raises `ConnectionError`, and
        it escapes `run_forever` — which only knows about `ProtocolError`
        — taking the process down. Runners are supposed to poll and
        reconnect (J-2); a routine core deploy must not require restarting
        the fleet. As `ProtocolError` this becomes an ordinary backoff.
        """
        try:
            return self._send(path, body, timeout_s=timeout_s)
        except requests.RequestException as exc:
            raise ProtocolError(f"{call}: transport failure ({exc})") from exc

    @staticmethod
    def _json(response: requests.Response) -> dict:
        try:
            data = response.json()
        except ValueError as exc:
            raise ProtocolError(
                f"core returned non-JSON body (status {response.status_code})",
                status=response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise ProtocolError(
                f"core returned non-object body (status {response.status_code})",
                status=response.status_code,
            )
        return data

    def _check(self, response: requests.Response, call: str) -> dict:
        if response.status_code == 409:
            raise LeaseLost(f"{call}: lease lost (409)")
        if response.status_code == 422:
            errors = []
            try:
                errors = list(self._json(response).get("errors", []))
            except ProtocolError:
                pass
            raise DeliveryRejected(f"{call}: delivery rejected (422)", errors=errors)
        if response.status_code >= 300:
            raise ProtocolError(
                f"{call}: unexpected status {response.status_code}",
                status=response.status_code,
            )
        return self._json(response)

    def _deliver(self, path: str, body: bytes, call: str, *, timeout_s: float) -> dict:
        """Terminal calls (complete/fail/defer): retry transient errors only."""
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._send(path, body, timeout_s=timeout_s)
            except requests.RequestException as exc:
                if attempt > self.deliver_retries:
                    raise ProtocolError(f"{call}: transport failure ({exc})") from exc
                logger.warning("%s: transport error, retrying (%d)", call, attempt)
                time.sleep(self.deliver_backoff_s * attempt)
                continue
            if response.status_code >= 500 and attempt <= self.deliver_retries:
                logger.warning("%s: core %d, retrying (%d)", call, response.status_code, attempt)
                time.sleep(self.deliver_backoff_s * attempt)
                continue
            return self._check(response, call)

    # -- the six wire calls (§6.1–§6.6) -----------------------------------

    def claim(
        self,
        *,
        runner_id: str,
        connectors: list[dict],
        classes: list[str],
        wait_s: int = 25,
    ) -> dict | None:
        """§6.1 long-poll claim; None when nothing matched (204)."""
        body = json.dumps({
            "runner_id": runner_id,
            "connectors": connectors,
            "classes": classes,
            "wait_s": wait_s,
        }).encode("utf-8")
        response = self._post("/v1/jobs/claim", body, timeout_s=wait_s + self.timeout_s, call="claim")
        if response.status_code == 204:
            return None
        return self._check(response, "claim")

    def start(self, job_id: str, lease_token: str) -> dict:
        body = json.dumps({"lease_token": lease_token}).encode("utf-8")
        response = self._post(f"/v1/jobs/{job_id}/start", body, timeout_s=self.timeout_s, call="start")
        return self._check(response, "start")

    def heartbeat(self, job_id: str, lease_token: str, progress: dict | None = None) -> dict:
        payload: dict = {"lease_token": lease_token}
        if progress is not None:
            payload["progress"] = progress
        body = json.dumps(payload).encode("utf-8")
        response = self._post(f"/v1/jobs/{job_id}/heartbeat", body, timeout_s=self.timeout_s, call="heartbeat")
        return self._check(response, "heartbeat")

    def complete_snapshot(self, job_id: str, lease_token: str, serialized: bytes) -> dict:
        """§6.4 with `result` spliced in as the SDK's canonical bytes."""
        body = (
            b'{"lease_token":' + json.dumps(lease_token).encode("utf-8")
            + b',"result":' + serialized.strip() + b"}"
        )
        return self._deliver(
            f"/v1/jobs/{job_id}/complete", body, "complete",
            timeout_s=max(self.timeout_s, 120.0),
        )

    def complete(self, job_id: str, lease_token: str, result: object) -> dict:
        """§6.4 for the interactive capabilities, whose `result` is the
        capability's own envelope (a dict), not canonical snapshot bytes.

        The core relays it to the blocked producer verbatim, so the
        serialization here is ordinary JSON — the byte-fidelity concern
        that shapes `complete_snapshot` applies to snapshot hashing only.
        """
        body = json.dumps({"lease_token": lease_token, "result": result}).encode("utf-8")
        return self._deliver(
            f"/v1/jobs/{job_id}/complete", body, "complete",
            timeout_s=max(self.timeout_s, 120.0),
        )

    def fail(self, job_id: str, lease_token: str, error: dict) -> dict:
        body = json.dumps({"lease_token": lease_token, "error": error}).encode("utf-8")
        return self._deliver(f"/v1/jobs/{job_id}/fail", body, "fail",
                             timeout_s=self.timeout_s)

    def defer(self, job_id: str, lease_token: str, retry_after_s: int, reason: dict) -> dict:
        body = json.dumps({
            "lease_token": lease_token,
            "retry_after_s": retry_after_s,
            "reason": reason,
        }).encode("utf-8")
        return self._deliver(f"/v1/jobs/{job_id}/defer", body, "defer",
                             timeout_s=self.timeout_s)
