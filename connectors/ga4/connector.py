"""The GA4 MetadataProvider (task 1.3, plan §3.2).

Five read-only GETs against one property, then a pure mapping
(mapping.py) into api_dimension / api_metric / api_event objects:

1. Admin `properties/{id}` — the source_properties facts (D-27)
2. Data API `properties/{id}/metadata` — standard + custom dimensions
   and metrics (the enumerating surface, D-23)
3. Admin `customDimensions` (paginated) — join/consistency only
4. Admin `customMetrics` (paginated) — custom-metric `scope`
5. Admin v1alpha `calculatedMetrics` (paginated) — `formula`
   (calculated metrics have not graduated to v1beta; D-22)
6. Admin `keyEvents` (paginated) — the api_event objects (D-25)

Quota policy per the manifest, honored by the SDK primitives; requests
that stay throttled after backoff raise `QuotaExceeded` → a J-5
deferral. Any other API failure maps to the §6.7 taxonomy with no
fallback (MP-1/CC-2) — the job fails and nothing is written.

Credentials: `credentials_file` (path to the service-account JSON key)
or `credentials_env` (env var holding the key JSON) — references only,
never key material in config files (D-28). Vault-reference resolution
stays a job-transport concern (D-14). Error messages never echo key
material (JC-8).

Documented source_properties keys (MP-2, additive only):
`property_id`, `display_name`, `time_zone`, `currency_code` — see
README and D-27.
"""

import time

from connectors.sdk import (
    Connector,
    IntrospectionResult,
    MetadataProvider,
    QuotaPolicy,
)
from connectors.ga4.client import GA4Client
from connectors.ga4.mapping import build_objects, source_properties

# Shared with the QueryExecutor (executor.py); re-exported here so
# existing importers of these names keep working.
from connectors.ga4.api import (  # noqa: F401
    ADMIN_API,
    DATA_API,
    MANIFEST,
    READONLY_SCOPE,
    _authorized_transport,
    _credentials,
)


class GA4Metadata(MetadataProvider):
    def __init__(self, transport_factory=None, *, sleep=time.sleep, rng=None):
        self._transport_factory = transport_factory or _authorized_transport
        self._sleep = sleep
        self._rng = rng

    def preflight(self, config: dict) -> dict:
        """The first GET a snapshot job makes, and nothing else.

        `properties/{id}` is call 1 of the six in `introspect`, so this
        exercises the whole credential path — service-account key loads,
        token mints, property is reachable and readable by this account
        — at the cost of one request. The client's own mapping does the
        classification: 401/403 becomes `AuthError`, which is what the
        Connections module turns into a re-auth prompt.
        """
        client = GA4Client(
            self._transport_factory(config),
            QuotaPolicy.from_rate_limit(MANIFEST.rate_limit),
            sleep=self._sleep,
            rng=self._rng,
        )
        pid = config["property_id"]
        prop = client.get_json(f"{ADMIN_API}/v1beta/properties/{pid}")
        return {
            "probed": True,
            "credential_tested": True,
            "property_id": pid,
            "display_name": prop.get("displayName"),
            "time_zone": prop.get("timeZone"),
        }

    def introspect(self, config: dict) -> IntrospectionResult:
        client = GA4Client(
            self._transport_factory(config),
            QuotaPolicy.from_rate_limit(MANIFEST.rate_limit),
            sleep=self._sleep,
            rng=self._rng,
        )
        pid = config["property_id"]
        prop = client.get_json(f"{ADMIN_API}/v1beta/properties/{pid}")
        metadata = client.get_json(f"{DATA_API}/v1beta/properties/{pid}/metadata")
        dims = client.paginate(
            f"{ADMIN_API}/v1beta/properties/{pid}/customDimensions", "customDimensions"
        )
        metrics = client.paginate(
            f"{ADMIN_API}/v1beta/properties/{pid}/customMetrics", "customMetrics"
        )
        calcs = client.paginate(
            f"{ADMIN_API}/v1alpha/properties/{pid}/calculatedMetrics", "calculatedMetrics"
        )
        events = client.paginate(f"{ADMIN_API}/v1beta/properties/{pid}/keyEvents", "keyEvents")
        return IntrospectionResult(
            system_class="api",
            objects=build_objects(metadata, dims, metrics, calcs, events),
            source_properties=source_properties(prop),
        )


from connectors.ga4.executor import GA4Executor  # noqa: E402  (avoids a cycle via api.py)

connector = Connector(
    manifest=MANIFEST, handlers={"metadata": GA4Metadata(), "query": GA4Executor()}
)
