"""GA4 HTTP layer: pacing, backoff, pagination, error taxonomy (D-28).

The connector speaks plain REST to the Data and Admin APIs (D-22). A
*transport* is anything with `get(url, params) -> (status, headers,
body)` — live runs use `AuthorizedTransport` over google-auth's
`AuthorizedSession`; the recorded-response test suite injects a fake.
Transport-level faults (network, TLS, token refresh) are raised by the
transport itself, already mapped to the taxonomy.

`GA4Client` owns the response-status mapping, honoring the manifest
quota policy (J-5, D-28):
- 429 / 403+RESOURCE_EXHAUSTED → token-bucket-paced backoff retries;
  still throttled after the schedule → `QuotaExceeded` (the runner
  defers, never fails);
- 5xx → same backoff schedule, then `SourceUnavailable` (retryable);
- 401/403 → `AuthError`; 400/404 → `ConfigError`; anything else
  unexpected → `SourceUnavailable`.

Error messages name the endpoint path, HTTP status, and API `status`
string only — never credential material or response bodies (JC-8).
"""

import random
import time
from typing import Callable, Protocol
from urllib.parse import urlsplit

import requests
from google.auth.exceptions import GoogleAuthError

from connectors.sdk import (
    AuthError,
    ConfigError,
    QuotaExceeded,
    QuotaPolicy,
    SourceUnavailable,
    TokenBucket,
    backoff_delays,
)


class Transport(Protocol):
    def get(self, url: str, params: dict | None = None) -> tuple[int, dict, dict | None]:
        """Return (HTTP status, headers, parsed-JSON body or None)."""

    def post(self, url: str, json_body: dict) -> tuple[int, dict, dict | None]:
        """Return (HTTP status, headers, parsed-JSON body or None).

        Needed by the QueryExecutor: the Data API's `runReport` is a
        POST, while every metadata endpoint the connector reads is a
        GET. Same status mapping applies to both (`GA4Client`).
        """


class AuthorizedTransport:
    """Live transport over google-auth's AuthorizedSession."""

    def __init__(self, session, *, timeout_s: int = 60):
        self._session = session
        self._timeout_s = timeout_s

    def get(self, url: str, params: dict | None = None) -> tuple[int, dict, dict | None]:
        return self._send("GET", url, params=params)

    def post(self, url: str, json_body: dict) -> tuple[int, dict, dict | None]:
        return self._send("POST", url, json_body=json_body)

    def _send(
        self, method: str, url: str, params: dict | None = None, json_body: dict | None = None
    ) -> tuple[int, dict, dict | None]:
        try:
            response = self._session.request(
                method, url, params=params, json=json_body, timeout=self._timeout_s
            )
        except GoogleAuthError as exc:
            # Token acquisition/refresh failed — the re-auth flow, not a retry.
            raise AuthError(
                f"GA4 credentials rejected while calling {_path(url)}: {type(exc).__name__}"
            ) from exc
        except requests.RequestException as exc:
            raise SourceUnavailable(
                f"cannot reach GA4 API at {_path(url)}: {type(exc).__name__}"
            ) from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        return response.status_code, dict(response.headers), body


def _path(url: str) -> str:
    return urlsplit(url).path


def _api_status(body: dict | None) -> str:
    if isinstance(body, dict):
        return body.get("error", {}).get("status", "")
    return ""


def _retry_after_s(headers: dict) -> int | None:
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return None
    return None


class GA4Client:
    def __init__(
        self,
        transport: Transport,
        policy: QuotaPolicy,
        *,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ):
        self._transport = transport
        self._policy = policy
        self._bucket = TokenBucket(policy, sleep=sleep)
        self._sleep = sleep
        self._rng = rng

    def get_json(self, url: str, params: dict | None = None) -> dict:
        """One logical GET, paced and retried per the manifest policy."""
        return self._json_call(lambda: self._transport.get(url, params), url)

    def post_json(self, url: str, json_body: dict) -> dict:
        """One logical POST (the Data API's `runReport`), same pacing,
        backoff, and status mapping as `get_json`."""
        return self._json_call(lambda: self._transport.post(url, json_body), url)

    def _json_call(self, send, url: str) -> dict:
        delays = backoff_delays(self._policy, rng=self._rng)
        while True:
            self._bucket.acquire()
            status, headers, body = send()
            path, api_status = _path(url), _api_status(body)

            if status == 200:
                if not isinstance(body, dict):
                    raise SourceUnavailable(f"malformed (non-JSON) 200 response from {path}")
                return body

            throttled = status == 429 or (status == 403 and api_status == "RESOURCE_EXHAUSTED")
            if throttled or 500 <= status <= 599:
                delay = next(delays, None)
                if delay is not None:
                    self._sleep(delay)
                    continue
                if throttled:
                    retry_after = _retry_after_s(headers)
                    raise QuotaExceeded(
                        f"GA4 quota exhausted at {path} ({status} {api_status or 'throttled'})",
                        retry_after_s=(
                            retry_after
                            if retry_after is not None
                            else self._policy.default_retry_after_s
                        ),
                        detail={"endpoint": path, "http_status": status},
                    )
                raise SourceUnavailable(
                    f"GA4 API error at {path} ({status} {api_status or 'server error'}) "
                    "after backoff retries"
                )

            if status in (401, 403):
                raise AuthError(
                    f"GA4 API denied access at {path} ({status} {api_status or 'denied'}); "
                    "check the service account's read access to the property"
                )
            if status in (400, 404):
                raise ConfigError(
                    f"GA4 API rejected the request at {path} ({status} "
                    f"{api_status or 'bad request'}); check property_id"
                )
            raise SourceUnavailable(f"unexpected {status} response from {path}")

    def paginate(self, url: str, items_key: str, *, page_size: int = 200) -> list[dict]:
        """Collect every page of an Admin API list endpoint."""
        items: list[dict] = []
        params: dict = {"pageSize": page_size}
        while True:
            page = self.get_json(url, params)
            items.extend(page.get(items_key, []))
            token = page.get("nextPageToken")
            if not token:
                return items
            params = {"pageSize": page_size, "pageToken": token}
