"""Shared connector SDK harness (consumed by tasks 1.2-1.4).

Implements the connector-side halves of three contracts:
- capability spec §3/CC-1 — manifest loading + validation (manifest.py)
  and manifest↔handler assembly (connector.py);
- capability spec §5 — the MetadataProvider rendering (providers.py):
  a connector implements `introspect(config)`; the harness owns the
  envelope, hashing, validation, canonicalization (emission.py);
- job spec §6.7/J-5/J-6 connector-side — the error taxonomy
  (errors.py) and the job engine with its transport seam (runner.py);
  local.py is the first transport (CLI, no core job API needed).

Out of scope by design: claims, leases, heartbeats, credential-vault
resolution — those arrive with the job-protocol transport and slot in
behind `run_job` without touching connector code.
"""

from connectors.sdk.connector import Connector, RegistrationError
from connectors.sdk.emission import EmittedSnapshot, emit_snapshot
from connectors.sdk.errors import (
    AuthError,
    Cancelled,
    ConfigError,
    ConnectorError,
    EmissionError,
    QuotaExceeded,
    SourceUnavailable,
)
from connectors.sdk.manifest import (
    CAPABILITY_JOB_TYPES,
    SUPPORTED_PROTOCOL_VERSION,
    SUPPORTED_SNAPSHOT_VERSION,
    Manifest,
    ManifestError,
    load_manifest,
)
from connectors.sdk.providers import IntrospectionResult, MetadataProvider
from connectors.sdk.quota import QuotaPolicy, TokenBucket, backoff_delays
from connectors.sdk.runner import Job, JobError, JobOutcome, run_job

__all__ = [
    "AuthError",
    "CAPABILITY_JOB_TYPES",
    "Cancelled",
    "ConfigError",
    "Connector",
    "ConnectorError",
    "EmissionError",
    "EmittedSnapshot",
    "IntrospectionResult",
    "Job",
    "JobError",
    "JobOutcome",
    "Manifest",
    "ManifestError",
    "MetadataProvider",
    "QuotaExceeded",
    "QuotaPolicy",
    "RegistrationError",
    "SourceUnavailable",
    "SUPPORTED_PROTOCOL_VERSION",
    "SUPPORTED_SNAPSHOT_VERSION",
    "TokenBucket",
    "backoff_delays",
    "emit_snapshot",
    "load_manifest",
    "run_job",
]
