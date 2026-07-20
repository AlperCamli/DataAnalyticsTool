"""Shared GSC API surface: transport, credentials, status mapping.

Split out of `connector.py` when the QueryExecutor arrived (CP-6/M2),
mirroring `connectors/ga4/api.py`: the MetadataProvider and the
QueryExecutor need the same authorized transport and the same response
status mapping, and having the executor import the connector module
(which registers the executor) would be a cycle. `connector.py`
re-exports these names, so existing importers are unaffected.

`searchAnalytics.query` is a POST while `sites.get` is a GET; both go
through `_json_call`, so the quota/backoff/error taxonomy (D-32) is
identical on both verbs.
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import urlsplit

import requests
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account

from connectors.sdk import (
    AuthError,
    ConfigError,
    QuotaExceeded,
    QuotaPolicy,
    SourceUnavailable,
    backoff_delays,
    load_manifest,
)

MANIFEST = load_manifest(Path(__file__).parent / "connector.yaml")

API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

UNVERIFIED = "siteUnverifiedUser"

# The fixed Search Analytics schema (D-30). Names are wire vocabulary
# verbatim; data_type is the declared {string, integer, double}
# convention, pinned by the 1.1 fixture's hashes (fixtures/gsc.json).
# Provenance: the Search Analytics API reference,
# https://developers.google.com/webmaster-tools/v1/searchanalytics/query
FIXED_DIMENSIONS: tuple[str, ...] = (
    "query",
    "page",
    "country",
    "device",
    "date",
    "searchAppearance",
)
FIXED_METRICS: tuple[tuple[str, str], ...] = (
    ("clicks", "integer"),
    ("impressions", "integer"),
    ("ctr", "double"),
    ("position", "double"),
)
DATA_STATES: tuple[str, ...] = ("all", "final")


class Transport(Protocol):
    def get(self, url: str, params: dict | None = None) -> tuple[int, dict, dict | None]:
        """Return (HTTP status, headers, parsed-JSON body or None)."""

    def post(self, url: str, json_body: dict) -> tuple[int, dict, dict | None]:
        """Return (HTTP status, headers, parsed-JSON body or None).

        `searchAnalytics.query` — the one operation the QueryExecutor
        runs — is a POST; the metadata path uses GET only.
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
                f"GSC credentials rejected while calling {_path(url)}: {type(exc).__name__}"
            ) from exc
        except requests.RequestException as exc:
            raise SourceUnavailable(
                f"cannot reach the Search Console API at {_path(url)}: {type(exc).__name__}"
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


def _credentials(config: dict) -> service_account.Credentials:
    if "credentials_file" in config:
        path = Path(config["credentials_file"])
        if not path.is_file():
            raise ConfigError(f"service-account key file not found: {path}")
        try:
            return service_account.Credentials.from_service_account_file(
                str(path), scopes=[READONLY_SCOPE]
            )
        except (ValueError, KeyError) as exc:
            raise ConfigError(
                f"service-account key file {path} could not be parsed "
                "(contents not echoed; check the key)"
            ) from exc
    env_var = config["credentials_env"]
    blob = os.environ.get(env_var)
    if not blob:
        raise ConfigError(
            f"environment variable {env_var!r} (config.credentials_env) is unset or empty"
        )
    try:
        return service_account.Credentials.from_service_account_info(
            json.loads(blob), scopes=[READONLY_SCOPE]
        )
    except (ValueError, KeyError) as exc:
        raise ConfigError(
            f"service-account key in ${env_var} could not be parsed "
            "(contents not echoed; check the key)"
        ) from exc


def _authorized_transport(config: dict) -> Transport:
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedTransport(AuthorizedSession(_credentials(config)))


def _get_json(
    transport: Transport,
    url: str,
    policy: QuotaPolicy,
    *,
    sleep: Callable[[float], None],
    rng: random.Random | None,
) -> dict:
    """One logical GET, retried per the manifest backoff policy (D-32)."""
    return _json_call(lambda: transport.get(url), url, policy, sleep=sleep, rng=rng)


def _post_json(
    transport: Transport,
    url: str,
    json_body: dict,
    policy: QuotaPolicy,
    *,
    sleep: Callable[[float], None],
    rng: random.Random | None,
) -> dict:
    """One logical POST (`searchAnalytics.query`), same policy as GET."""
    return _json_call(
        lambda: transport.post(url, json_body), url, policy, sleep=sleep, rng=rng
    )


def _json_call(
    send,
    url: str,
    policy: QuotaPolicy,
    *,
    sleep: Callable[[float], None],
    rng: random.Random | None,
) -> dict:
    delays = backoff_delays(policy, rng=rng)
    while True:
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
                sleep(delay)
                continue
            if throttled:
                retry_after = _retry_after_s(headers)
                raise QuotaExceeded(
                    f"GSC quota exhausted at {path} ({status} {api_status or 'throttled'})",
                    retry_after_s=(
                        retry_after
                        if retry_after is not None
                        else policy.default_retry_after_s
                    ),
                    detail={"endpoint": path, "http_status": status},
                )
            raise SourceUnavailable(
                f"Search Console API error at {path} ({status} "
                f"{api_status or 'server error'}) after backoff retries"
            )

        if status in (401, 403):
            raise AuthError(
                f"Search Console denied access at {path} ({status} "
                f"{api_status or 'denied'}); check the service-account key and that "
                "the account is a user of the property"
            )
        if status in (400, 404):
            raise ConfigError(
                f"Search Console rejected the request at {path} ({status} "
                f"{api_status or 'bad request'}); check config.site_url matches the "
                "property exactly as registered"
            )
        raise SourceUnavailable(f"unexpected {status} response from {path}")


