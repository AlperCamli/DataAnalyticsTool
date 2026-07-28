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
from hashlib import sha256

from connectors.sdk.encoding import json_row


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


# ---------------------------------------------------------------------------
# QueryExecutor (capability spec §6) — job type `execute`


@dataclass(frozen=True)
class Guardrails:
    """The §4 guardrail envelope as the executor sees it.

    The gateway is authority and attaches these pre-enqueue (CI-3), but
    QE-1 makes the executor enforce locally *regardless* — so `parse`
    never widens anything on the way in. A payload with guardrails
    missing, partial, or nonsensically large does not yield an
    unbounded execution: it yields the conservative floor below. This
    is the CC-3 property, and it is why the defaults are not "no
    limit".
    """

    row_cap: int = 1000
    timeout_s: int = 30
    statement_class: str = "select-only"
    validated_against: str | None = None

    # Ceilings the executor will not exceed even if a payload asks it to.
    MAX_ROW_CAP = 1_000_000
    MAX_TIMEOUT_S = 300

    @classmethod
    def parse(cls, raw: object) -> "Guardrails":
        defaults = cls()
        if not isinstance(raw, dict):
            return defaults

        def bounded(key: str, fallback: int, ceiling: int) -> int:
            value = raw.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                return fallback
            return min(value, ceiling)

        # `statement_class` is never read from the payload as a widening
        # signal: select-only is the only class this SDK executes, so an
        # absent or forged value cannot unlock DML (QE-1).
        return cls(
            row_cap=bounded("row_cap", defaults.row_cap, cls.MAX_ROW_CAP),
            timeout_s=bounded("timeout_s", defaults.timeout_s, cls.MAX_TIMEOUT_S),
            statement_class="select-only",
            validated_against=(
                raw["validated_against"] if isinstance(raw.get("validated_against"), str) else None
            ),
        )


@dataclass(frozen=True)
class Identity:
    """§4 identity envelope. Data for tagging and target-side mapping —
    never an authentication credential (CI-4)."""

    subject: str = "unknown"
    roles: tuple = ()
    display: str | None = None
    session_id: str | None = None
    intent: str | None = None

    @classmethod
    def parse(cls, raw: object) -> "Identity":
        if not isinstance(raw, dict):
            return cls()
        roles = raw.get("roles")
        return cls(
            subject=raw.get("subject") or "unknown",
            roles=tuple(r for r in roles if isinstance(r, str)) if isinstance(roles, list) else (),
            display=raw.get("display"),
            session_id=raw.get("session_id"),
            intent=raw.get("intent"),
        )

    def intent_hash(self) -> str:
        """QE-2: only the hash rides the wire; the text stays in audit."""
        return sha256((self.intent or "").encode("utf-8")).hexdigest()[:16]

    def comment_tag(self) -> str:
        """The QE-2 leading comment. Every component is sanitized: a
        subject or session id containing `*/` must not be able to close
        the comment and inject statement text."""

        def clean(value: str) -> str:
            return "".join(c for c in value if c.isalnum() or c in "@.:_-|+")[:120] or "unknown"

        return (
            f"/* contextlayer user={clean(self.subject)} "
            f"session={clean(self.session_id or 'none')} "
            f"intent={clean(self.intent_hash())} */"
        )


@dataclass(frozen=True)
class ExecuteRequest:
    """§6 request, both dialects (CI-6)."""

    dialect: str
    statement: str | None = None
    params: tuple = ()
    operation: str | None = None
    body: dict | None = None

    @classmethod
    def parse(cls, raw: object) -> "ExecuteRequest":
        if not isinstance(raw, dict):
            raise ValueError("request must be an object")
        dialect = raw.get("dialect")
        if dialect not in ("sql", "api"):
            raise ValueError(f"request.dialect must be 'sql' or 'api', got {dialect!r}")
        params = raw.get("params")
        return cls(
            dialect=dialect,
            statement=raw.get("statement"),
            params=tuple(params) if isinstance(params, list) else (),
            operation=raw.get("operation"),
            body=raw.get("body") if isinstance(raw.get("body"), dict) else None,
        )


@dataclass(frozen=True)
class ExecuteResult:
    """§6 result. `truncated` is an explicit fact, never silent (CI-7)."""

    columns: list[dict]
    rows: list[list]
    row_count: int
    truncated: bool
    duration_ms: int
    source: dict

    def to_json(self) -> dict:
        # QE-5 is enforced at the boundary as well as in the executors, so
        # a connector that forgets it is still conformant rather than a
        # crash at delivery. json_value is idempotent, so the executors
        # that already encoded pay nothing but the walk.
        return {
            "columns": self.columns,
            "rows": [json_row(row) for row in self.rows],
            "row_count": self.row_count,
            "truncated": self.truncated,
            "duration_ms": self.duration_ms,
            "source": self.source,
        }


class QueryExecutor(ABC):
    """Handler for job type `execute` (capability `query`).

    Duties are normative in capability spec §6: local guardrail
    enforcement (QE-1) independent of what the payload carries,
    comment tagging (QE-2), parameterized execution (QE-3), and
    interactive quota as a terminal `guardrail` error rather than a
    deferral (QE-4) — the user is waiting.
    """

    @abstractmethod
    def execute(
        self,
        config: dict,
        request: ExecuteRequest,
        guardrails: Guardrails,
        identity: Identity,
    ) -> ExecuteResult:
        """Execute one validated request and return the capped result."""

    def preflight(self, config: dict) -> None:
        """Optional startup check, run before the executor serves any
        traffic. Raise `ConfigError` to refuse service — the postgres
        executor uses this to verify its role cannot write (G3)."""


@dataclass(frozen=True)
class PublishRequest:
    """§8.2 payload members the adapter consumes.

    The artifact is opaque-but-versioned to this layer: the engine gates
    on `artifact_version` against the adapter's declared support
    (capability code `artifact_version_unsupported`), and everything
    else about its interior is the formats spec's business — the server
    validated it before enqueue (F-7/MT-10); the adapter re-checks only
    what it structurally depends on (defense in depth, CI-3 spirit).
    """

    artifact: dict
    target: str
    #: Two-call contract members for `create_report: api` adapters
    #: (capability §8.2 amendment / report-authoring §7). `mode` is None
    #: exactly when the adapter is a single-shot (template_link/full)
    #: publisher; api adapters receive "deliver_model" or "attest".
    mode: str | None = None
    #: deliver_model: query name → capability §6 execute result —
    #: gateway-executed, the only thing that may feed a model (RA-2).
    results: dict | None = None
    #: deliver_model: the prior delivery's `results`, for restoring
    #: complete-or-previous after a mid-delivery failure (§5 / AT-8).
    previous: dict | None = None
    #: attest: {report_id, definition_hash} from the verified deploy.
    attestation: dict | None = None

    @classmethod
    def parse(
        cls,
        artifact: object,
        target: object,
        mode: object = None,
        results: object = None,
        previous: object = None,
        attestation: object = None,
    ) -> "PublishRequest":
        if not isinstance(artifact, dict):
            raise ValueError("payload.artifact must be an object")
        if not isinstance(target, str) or not target:
            raise ValueError("payload.target must be a non-empty string")
        if mode is not None and mode not in ("deliver_model", "attest"):
            raise ValueError(
                "payload.mode must be 'deliver_model' or 'attest' when present "
                "(capability §8.2 amendment)"
            )
        for name, value in (("results", results), ("previous", previous),
                            ("attestation", attestation)):
            if value is not None and not isinstance(value, dict):
                raise ValueError(f"payload.{name} must be an object when present")
        return cls(
            artifact=artifact,
            target=target,
            mode=mode if isinstance(mode, str) else None,
            results=results if isinstance(results, dict) else None,
            previous=previous if isinstance(previous, dict) else None,
            attestation=attestation if isinstance(attestation, dict) else None,
        )

    @property
    def artifact_version(self) -> str | None:
        version = self.artifact.get("artifact_version")
        return version if isinstance(version, str) else None


@dataclass(frozen=True)
class PublishResult:
    """§8.2 result. PB-2: every created object carries a stable id +
    URL; PB-3: `pending_human_steps` is mandatory whenever
    `mode != "full"` (the engine enforces it, so a forgetful adapter is
    a loud failure rather than a silently misleading journey); PB-4:
    visual-kind substitutions ride in `detail.visual_substitutions`.
    """

    mode: str  # "full" | "template_link" | "instructions"
    created: list[dict]
    pending_human_steps: list[str]
    backing: list[dict]
    detail: dict

    def to_json(self) -> dict:
        return {
            "mode": self.mode,
            "created": self.created,
            "pending_human_steps": self.pending_human_steps,
            "backing": self.backing,
            "detail": self.detail,
        }


class Publisher(ABC):
    """Handler for job type `publish` (capability `publish`).

    Duties are normative in capability spec §8: mode consistent with
    the manifest's declared flags (PB-1 — attempting beyond them is
    `config_error`, a core/release bug, not a runtime surprise);
    idempotency per `(artifact.id, target)` (PB-2/CC-7); mandatory
    `pending_human_steps` off the `full` path (PB-3); substitutions
    recorded, never silent (PB-4).
    """

    #: artifact_version values this adapter can parse (§8.2 gate).
    SUPPORTED_ARTIFACT_VERSIONS: tuple[str, ...] = ("1",)

    @abstractmethod
    def publish(
        self,
        config: dict,
        request: PublishRequest,
        identity: Identity,
        flags: dict,
    ) -> PublishResult:
        """Publish one artifact to `request.target` and return the §8.2
        result. `flags` is the manifest's `capabilities.publish` block —
        the static side of CI-5; a tenant probe may only ever narrow it,
        so an adapter honoring `flags` never overstates."""
