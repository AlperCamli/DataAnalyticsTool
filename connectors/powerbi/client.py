"""Power BI HTTP layer: pinned-gate emission, tokens, backoff, taxonomy.

Every request leaves through `PowerBIClient.call`, which builds the URL
with `reference.pinned_endpoint`, re-checks it with `pinned_request`,
and validates query parameters against the pinned set — the AT-7
guarantee that no code path (including future ones) can emit an
unpinned Microsoft request. Fixture runs may rewrite the HOST after the
gate (config `*_base_override`), never the path: the stub serves the
pinned shapes or the test fails, which is the point.

Status mapping follows the house taxonomy (job spec §6.7, the GA4
client's pattern): 429 → paced retries honoring Retry-After, then
QuotaExceeded (interactive publish turns that into a terminal
guardrail, capability QE-4 posture); 5xx → bounded backoff then
SourceUnavailable; 401/403 → AuthError; 400/404/409 → ConfigError.
Messages name the endpoint, status, and the response's errorCode where
present — never credential material or full bodies (JC-8).
"""

from __future__ import annotations

import time
from typing import Callable, Mapping, Protocol
from urllib.parse import urlencode

from connectors.powerbi import reference as ref
from connectors.sdk.errors import AuthError, ConfigError, QuotaExceeded, SourceUnavailable


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        json_body: dict | None = None,
        form_data: Mapping[str, str] | None = None,
    ) -> tuple[int, Mapping[str, str], dict | list | None]:
        """Return (status, response headers, parsed JSON body or None)."""


class RequestsTransport:
    def __init__(self, timeout_s: int = 60):
        self._timeout_s = timeout_s

    def request(self, method, url, headers=None, json_body=None, form_data=None):
        import requests

        response = requests.request(
            method, url, headers=dict(headers or {}),
            json=json_body, data=dict(form_data) if form_data else None,
            timeout=self._timeout_s,
        )
        try:
            body = response.json() if response.content else None
        except ValueError:
            body = None
        return response.status_code, response.headers, body


_RETRY_SCHEDULE_S = (1.0, 2.0, 4.0)


def _error_code(body: object) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return error["code"]
        if isinstance(body.get("errorCode"), str):
            return body["errorCode"]
    return ""


class PowerBIClient:
    """One client, two resources: Power BI (push/dataset/report reads)
    and Fabric (report definitions). Tokens are acquired per scope via
    the pinned client-credentials endpoint and cached until near
    expiry."""

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        transport: Transport | None = None,
        base_overrides: Mapping[str, str] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._transport = transport or RequestsTransport()
        #: canonical base -> replacement host base (fixture stubs only).
        self._base_overrides = dict(base_overrides or {})
        self._sleep = sleeper
        self._tokens: dict[str, tuple[str, float]] = {}

    # --- token ---------------------------------------------------------------

    def _token(self, scope: str) -> str:
        cached = self._tokens.get(scope)
        if cached and cached[1] > time.monotonic() + 60:
            return cached[0]
        method, url = ref.pinned_endpoint("token", tenantId=self._tenant_id)
        ref.pinned_request(method, url)
        status, _, body = self._transport.request(
            method, self._rewrite(url),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            form_data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": scope,
            },
        )
        if status != 200 or not isinstance(body, dict) or not body.get("access_token"):
            description = str((body or {}).get("error_description", "")).split("\n")[0]
            raise AuthError(
                f"token acquisition for scope {scope} failed (HTTP {status})"
                + (f": {description}" if description else "")
            )
        token = str(body["access_token"])
        expires_in = body.get("expires_in")
        ttl = float(expires_in) if isinstance(expires_in, (int, float)) else 600.0
        self._tokens[scope] = (token, time.monotonic() + ttl)
        return token

    def _rewrite(self, url: str) -> str:
        """Fixture-only host rewrite, applied AFTER the pinned gate so
        the emitted path shape is always the verified one."""
        for canonical, override in self._base_overrides.items():
            if url.startswith(canonical):
                return override + url[len(canonical):]
        return url

    # --- the one exit --------------------------------------------------------

    def call(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str] | None = None,
        query: Mapping[str, str] | None = None,
        json_body: dict | None = None,
        scope: str = ref.PBI_SCOPE,
        expect: tuple[int, ...] = (200,),
    ) -> tuple[int, Mapping[str, str], dict | list | None]:
        """Emit one pinned request with retries; refuse anything the
        reference module does not document; map terminal statuses to
        the taxonomy."""
        method, url = ref.pinned_endpoint(endpoint, **dict(params or {}))
        ref.pinned_request(method, url)
        if query:
            ref.pinned_query_params(endpoint, query)
            url = f"{url}?{urlencode(dict(query))}"
        token = self._token(scope)

        attempts = 0
        while True:
            status, headers, body = self._transport.request(
                method, self._rewrite(url),
                headers={"Authorization": f"Bearer {token}",
                         **({"Content-Type": "application/json"} if json_body is not None else {})},
                json_body=json_body,
            )
            if status in expect:
                return status, headers, body
            if status == 429:
                retry_after = _retry_after_s(headers)
                if attempts < len(_RETRY_SCHEDULE_S):
                    self._sleep(retry_after or _RETRY_SCHEDULE_S[attempts])
                    attempts += 1
                    continue
                raise QuotaExceeded(
                    f"{endpoint} throttled (HTTP 429) after {attempts} retries",
                    retry_after_s=int(retry_after or 60),
                )
            if 500 <= status <= 599:
                if attempts < len(_RETRY_SCHEDULE_S):
                    self._sleep(_RETRY_SCHEDULE_S[attempts])
                    attempts += 1
                    continue
                raise SourceUnavailable(
                    f"{endpoint} failed (HTTP {status}) after {attempts} retries"
                )
            code = _error_code(body)
            suffix = f" [{code}]" if code else ""
            if status in (401, 403):
                raise AuthError(f"{endpoint} refused (HTTP {status}){suffix}")
            raise ConfigError(f"{endpoint} rejected (HTTP {status}){suffix}")

    # --- Fabric LRO ----------------------------------------------------------

    def await_operation(
        self,
        headers: Mapping[str, str],
        *,
        scope: str = ref.FABRIC_SCOPE,
        max_wait_s: float = 300.0,
    ) -> None:
        """Poll a Fabric 202 to a terminal state per the pinned LRO
        contract (Location / x-ms-operation-id / Retry-After)."""
        operation_id = _header(headers, "x-ms-operation-id")
        if not operation_id:
            raise SourceUnavailable("Fabric 202 carried no x-ms-operation-id header")
        waited = 0.0
        while True:
            delay = float(_header(headers, "Retry-After") or 2)
            delay = min(delay, max(0.0, max_wait_s - waited)) or 1.0
            self._sleep(delay)
            waited += delay
            _, headers, body = self.call(
                "fabric.operation_state", params={"operationId": operation_id}, scope=scope,
            )
            status_value = str((body or {}).get("status", "")) if isinstance(body, dict) else ""
            if status_value == "Succeeded":
                return
            if status_value == "Failed":
                error = (body or {}).get("error") if isinstance(body, dict) else None
                raise SourceUnavailable(
                    f"Fabric operation {operation_id} failed"
                    + (f" [{_error_code({'error': error})}]" if error else "")
                )
            if waited >= max_wait_s:
                raise SourceUnavailable(
                    f"Fabric operation {operation_id} still {status_value or 'running'} "
                    f"after {int(waited)}s"
                )


def _retry_after_s(headers: Mapping[str, str]) -> float | None:
    raw = _header(headers, "Retry-After")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return str(value)
    return ""
