"""Capability handler interfaces (informative renderings, CI-1).

The normative contract is the JSON payload/result shape per job type;
these classes are the Python SDK's rendering of it. A connector
implements `introspect(config)` and returns facts only — the harness
owns everything around it: envelope assembly, `schema_hash`
computation, validation, canonicalization, and emission (runner.py,
emission.py).

MP-1 falls out of the split: `source_mode` is stamped by the harness
from `config["mode"]`, so a connector cannot silently satisfy one mode
from another — if the requested mode is unavailable it must raise
`SourceUnavailable` instead.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IntrospectionResult:
    """What a MetadataProvider knows first-hand: facts, no envelope.

    `objects` are snapshot objects per snapshot spec §4 *without*
    `schema_hash` (the harness computes it via the 1.1 library; a
    connector-supplied hash is verified, never trusted).
    `source_properties` keys must be documented per connector and
    evolve additively (MP-2). All free text verbatim from source (S-8).
    """

    system_class: str  # "sql" | "api"
    objects: list[dict]
    source_properties: dict | None = field(default=None)


class MetadataProvider(ABC):
    """Handler for job type `snapshot` (capability `metadata`).

    One call per job: any exception fails the whole job and nothing is
    emitted (S-6 all-or-nothing). Raise the errors.py taxonomy for
    classified failures; anything else maps to `internal`.
    """

    @abstractmethod
    def introspect(self, config: dict) -> IntrospectionResult:
        """Introspect the source described by `config` (already
        validated against the manifest's config_schema; `config["mode"]`
        is one of the manifest's declared metadata modes)."""
