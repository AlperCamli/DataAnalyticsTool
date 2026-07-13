"""The GSC MetadataProvider (task 1.4, plan §3.3).

The Search Console schema is fixed — the API exposes no metadata
endpoint — so the estate is a provenance-pinned constant table (D-30):
six `api_dimension` and four `api_metric` objects whose names are the
Search Analytics wire vocabulary verbatim (dimension request values,
metric response fields). Descriptions are `null`: Google's reference
prose never crosses any wire, so it is not a snapshot fact (S-8,
D-30) — the human definitions belong to the generator's GSC template.

The live contribution is one read-only GET — `sites.get` on the
configured property — feeding the envelope (D-31). An unverified
property fails `source_unavailable` (retryable: verification is
source-side state a retry can find fixed), and per MP-1/CC-2 any
failure fails the whole job with nothing written (S-6).

Credentials: `credentials_file` / `credentials_env`, the same
indirection as GA4 (D-28); vault resolution stays a job-transport
concern (D-14). Error messages carry the endpoint path, HTTP status,
and API `status` string only — never key material (JC-8).

Documented source_properties keys (MP-2, additive only):
- `properties` — list (exactly one entry in v1: the configured
  property) of `site_url` (verbatim `siteUrl`), `permission_level`
  (verbatim `permissionLevel`), `verified` (derived:
  `permissionLevel != "siteUnverifiedUser"`).
- `data_freshness` — `data_states`: the Search Analytics `dataState`
  request vocabulary (`all` reaches fresh-but-provisional rows).
See README and D-31.
"""

import json
import os
import random
import time
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import quote, urlsplit

import requests
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import service_account

from connectors.sdk import (
    AuthError,
    ConfigError,
    Connector,
    IntrospectionResult,
    MetadataProvider,
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


def fixed_schema_objects() -> list[dict]:
    def object_for(kind: str, name: str, data_type: str) -> dict:
        return {
            "kind": kind,
            "schema": "standard",
            "name": name,
            "description": None,
            "columns": [],
            "keys": {},
            "stats": {"data_type": data_type},
        }

    return [object_for("api_dimension", name, "string") for name in FIXED_DIMENSIONS] + [
        object_for("api_metric", name, data_type) for name, data_type in FIXED_METRICS
    ]


class Transport(Protocol):
    def get(self, url: str, params: dict | None = None) -> tuple[int, dict, dict | None]:
        """Return (HTTP status, headers, parsed-JSON body or None)."""


class AuthorizedTransport:
    """Live transport over google-auth's AuthorizedSession."""

    def __init__(self, session, *, timeout_s: int = 60):
        self._session = session
        self._timeout_s = timeout_s

    def get(self, url: str, params: dict | None = None) -> tuple[int, dict, dict | None]:
        try:
            response = self._session.get(url, params=params, timeout=self._timeout_s)
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
    delays = backoff_delays(policy, rng=rng)
    while True:
        status, headers, body = transport.get(url)
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


class GscMetadata(MetadataProvider):
    def __init__(self, transport_factory=None, *, sleep=time.sleep, rng=None):
        self._transport_factory = transport_factory or _authorized_transport
        self._sleep = sleep
        self._rng = rng

    def introspect(self, config: dict) -> IntrospectionResult:
        site_url = config["site_url"]
        site = _get_json(
            self._transport_factory(config),
            f"{API_BASE}/sites/{quote(site_url, safe='')}",
            QuotaPolicy.from_rate_limit(MANIFEST.rate_limit),
            sleep=self._sleep,
            rng=self._rng,
        )
        if not isinstance(site.get("siteUrl"), str) or not isinstance(
            site.get("permissionLevel"), str
        ):
            raise SourceUnavailable(
                f"sites.get returned an unexpected shape for {site_url!r} "
                "(missing siteUrl/permissionLevel)"
            )
        permission = site["permissionLevel"]
        if permission == UNVERIFIED:
            raise SourceUnavailable(
                f"property {site['siteUrl']!r} is not verified for this service "
                "account; verify it in Search Console and retry"
            )
        return IntrospectionResult(
            system_class="api",
            objects=fixed_schema_objects(),
            source_properties={
                "properties": [
                    {
                        "site_url": site["siteUrl"],
                        "permission_level": permission,
                        "verified": permission != UNVERIFIED,
                    }
                ],
                "data_freshness": {"data_states": list(DATA_STATES)},
            },
        )


connector = Connector(manifest=MANIFEST, handlers={"metadata": GscMetadata()})
