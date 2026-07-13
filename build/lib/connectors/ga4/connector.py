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

import json
import os
import time
from pathlib import Path

from google.oauth2 import service_account

from connectors.sdk import (
    ConfigError,
    Connector,
    IntrospectionResult,
    MetadataProvider,
    QuotaPolicy,
    load_manifest,
)
from connectors.ga4.client import AuthorizedTransport, GA4Client, Transport
from connectors.ga4.mapping import build_objects, source_properties

MANIFEST = load_manifest(Path(__file__).parent / "connector.yaml")

DATA_API = "https://analyticsdata.googleapis.com"
ADMIN_API = "https://analyticsadmin.googleapis.com"
READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


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


class GA4Metadata(MetadataProvider):
    def __init__(self, transport_factory=None, *, sleep=time.sleep, rng=None):
        self._transport_factory = transport_factory or _authorized_transport
        self._sleep = sleep
        self._rng = rng

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


connector = Connector(manifest=MANIFEST, handlers={"metadata": GA4Metadata()})
