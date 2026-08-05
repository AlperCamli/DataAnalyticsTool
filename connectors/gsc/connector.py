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

import time
from urllib.parse import quote

from connectors.sdk import (
    Connector,
    IntrospectionResult,
    MetadataProvider,
    QuotaPolicy,
    SourceUnavailable,
)

# Shared with the QueryExecutor (executor.py); re-exported here so
# existing importers of these names keep working.
from connectors.gsc.api import (  # noqa: F401
    API_BASE,
    DATA_STATES,
    FIXED_DIMENSIONS,
    FIXED_METRICS,
    MANIFEST,
    READONLY_SCOPE,
    UNVERIFIED,
    AuthorizedTransport,
    Transport,
    _api_status,
    _authorized_transport,
    _credentials,
    _get_json,
    _path,
    _retry_after_s,
)


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


class GscMetadata(MetadataProvider):
    def __init__(self, transport_factory=None, *, sleep=time.sleep, rng=None):
        self._transport_factory = transport_factory or _authorized_transport
        self._sleep = sleep
        self._rng = rng

    def preflight(self, config: dict) -> dict:
        """`sites.get` — which is the whole live contribution anyway.

        The snapshot job's one API call, run on its own: it proves the
        key loads, the token mints, and the service account is a user of
        this property. The verification check is the same refusal
        `introspect` makes, because an unverified property is a
        connection that cannot work, and a probe that passed on one
        would be worse than no probe.
        """
        site_url = config["site_url"]
        site = _get_json(
            self._transport_factory(config),
            f"{API_BASE}/sites/{quote(site_url, safe='')}",
            QuotaPolicy.from_rate_limit(MANIFEST.rate_limit),
            sleep=self._sleep,
            rng=self._rng,
        )
        permission = site.get("permissionLevel")
        if not isinstance(permission, str):
            raise SourceUnavailable(
                f"sites.get returned an unexpected shape for {site_url!r} "
                "(missing permissionLevel)"
            )
        if permission == UNVERIFIED:
            raise SourceUnavailable(
                f"property {site.get('siteUrl', site_url)!r} is not verified for this "
                "service account; verify it in Search Console and retry"
            )
        return {
            "probed": True,
            "credential_tested": True,
            "site_url": site.get("siteUrl", site_url),
            "permission_level": permission,
            "verified": True,
        }

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


from connectors.gsc.executor import GscExecutor  # noqa: E402  (avoids a cycle via api.py)

connector = Connector(
    manifest=MANIFEST, handlers={"metadata": GscMetadata(), "query": GscExecutor()}
)
