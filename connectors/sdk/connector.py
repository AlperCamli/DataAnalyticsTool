"""Connector assembly: manifest + handlers, checked against each other.

Completes CC-1: `load_manifest` proves the file; assembly proves the
code — every declared capability has a handler and every handler backs
a declared capability (an undeclared handler would never be claim-
matched, so it is a release mistake, not a latent feature). The
manifest itself stays spec-pure (§3 shape, no Python entry-point
field); binding a manifest to code is this SDK-local object, addressed
on the CLI as MODULE:ATTR.
"""

from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from connectors.sdk.manifest import CAPABILITY_JOB_TYPES, Manifest, load_manifest
from connectors.sdk.providers import MetadataProvider, QueryExecutor


class RegistrationError(Exception):
    """Declared capabilities and registered handlers do not match (CC-1)."""


class Connector:
    def __init__(self, manifest: Manifest | str | Path, handlers: Mapping[str, object]):
        self.manifest = (
            manifest if isinstance(manifest, Manifest) else load_manifest(manifest)
        )
        problems: list[str] = []
        declared = set(self.manifest.capabilities)
        provided = set(handlers)
        for capability in sorted(declared - provided):
            problems.append(
                f"declared capability {capability!r} (job type "
                f"{CAPABILITY_JOB_TYPES[capability]!r}) has no registered handler"
            )
        for capability in sorted(provided - declared):
            problems.append(
                f"handler registered for undeclared capability {capability!r} "
                "— declare it in the manifest or drop the handler"
            )
        if "metadata" in provided and not isinstance(
            handlers["metadata"], MetadataProvider
        ):
            problems.append(
                "metadata handler must implement MetadataProvider.introspect"
            )
        if "query" in provided and not isinstance(handlers["query"], QueryExecutor):
            problems.append("query handler must implement QueryExecutor.execute")
        if problems:
            raise RegistrationError(
                f"connector {self.manifest.name!r}: " + "; ".join(problems)
            )
        self.handlers: Mapping[str, object] = MappingProxyType(dict(handlers))
