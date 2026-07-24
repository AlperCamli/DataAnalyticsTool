"""Shared GA4 API surface: manifest, endpoints, credentials, transport.

Split out of `connector.py` when the QueryExecutor arrived (CP-6/M2):
both the MetadataProvider and the QueryExecutor need the same manifest,
endpoints, and authorized transport, and having the executor import the
connector module (which registers the executor) would be a cycle.
`connector.py` re-exports these names, so existing importers are
unaffected.

Credential handling is unchanged and stays reference-only (D-28):
`credentials_file` (path) or `credentials_env` (env var holding the key
JSON). Parse failures never echo the contents.
"""

import json
import os
from pathlib import Path

from google.oauth2 import service_account

from connectors.sdk import ConfigError, load_manifest
from connectors.ga4.client import AuthorizedTransport, Transport

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
