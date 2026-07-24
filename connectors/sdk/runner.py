"""Job execution engine — the transport-pluggable seam.

`run_job(connector, job) -> JobOutcome` is a pure engine: it neither
claims work nor disposes of results. A *transport* is whatever obtains
a `Job` and disposes of the outcome — today the local CLI (local.py);
later the job-protocol runner maps the same outcome onto the wire
calls it mirrors (`complete` / `fail` / `defer`, job spec §6.4-§6.6)
without touching connector code. Leases, claims, and heartbeats are
deliberately absent: they belong to that future transport.

All-or-nothing (S-6) lives here: introspection is one call; any
exception fails the whole job and nothing is emitted. Quota maps to a
deferral, not a failure (J-5).
"""

import logging
import traceback
import uuid
from dataclasses import dataclass, field

from connectors.sdk.connector import Connector
from connectors.sdk.emission import EmittedSnapshot, config_problems, emit_snapshot
from connectors.sdk.errors import ConnectorError, GuardrailViolation, QuotaExceeded
from connectors.sdk.providers import (
    ExecuteRequest,
    ExecuteResult,
    Guardrails,
    Identity,
    IntrospectionResult,
    PublishRequest,
    PublishResult,
)
from connectors.sdk.redact import redact_deep, redact_text

logger = logging.getLogger("connectors.sdk.runner")


@dataclass(frozen=True)
class Job:
    """The slice of the §4.1 job record the engine needs.

    `credentials` carries vault references only (J-4); resolution is a
    transport/runner concern and is not wired until a connector needs
    it (task 1.2 live mode).
    """

    job_id: str
    config: dict
    type: str = "snapshot"
    credentials: tuple = ()
    # `execute` payload members (capability §6); unused by `snapshot`.
    request: dict | None = None
    guardrails: dict | None = None
    identity: dict | None = None
    # `publish` payload members (capability §8.2); unused elsewhere.
    artifact: dict | None = None
    target: str | None = None

    @classmethod
    def local(cls, config: dict) -> "Job":
        return cls(job_id=f"local-{uuid.uuid4().hex}", config=config)


@dataclass(frozen=True)
class JobError:
    code: str
    message: str
    retryable: bool
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class JobOutcome:
    """Mirrors the three terminal wire calls: complete / fail / defer.

    succeeded → `snapshot` set; failed → `error` set; deferred →
    `retry_after_s` set and `error` carries the §6.6 reason.
    """

    status: str  # "succeeded" | "failed" | "deferred"
    snapshot: EmittedSnapshot | None = None
    error: JobError | None = None
    retry_after_s: int | None = None
    # Set instead of `snapshot` when an interactive capability succeeds;
    # delivered inline as the §6.4 `result` envelope.
    result: dict | None = None


def _job_error(code: str, message: str, retryable: bool, detail: dict | None = None) -> JobError:
    """Build a JobError with credential-shaped strings scrubbed from the
    message and detail (job §7 / review F3 / D-66 point 2): a driver
    exception that echoes a resolved DSN must not travel the `fail` wire
    call into `jobs.error` / `health_events.detail`."""
    return JobError(code, redact_text(message), retryable, redact_deep(dict(detail or {})))


def _failed(exc: ConnectorError) -> JobOutcome:
    return JobOutcome(
        status="failed",
        error=_job_error(exc.code, str(exc), exc.retryable, dict(exc.detail)),
    )


def run_job(connector: Connector, job: Job, *, captured_at: str | None = None) -> JobOutcome:
    """Execute one job, dispatched by type."""
    if job.type == "execute":
        return _run_execute(connector, job)
    if job.type == "publish":
        return _run_publish(connector, job)
    if job.type != "snapshot":
        raise ValueError(f"no engine for job type {job.type!r} in this SDK version")

    manifest = connector.manifest
    if "metadata" not in connector.handlers:
        return JobOutcome(
            status="failed",
            error=_job_error(
                "config_error",
                f"connector {manifest.name!r} does not declare the metadata capability",
                retryable=False,
            ),
        )
    problems = config_problems(manifest, job.config)
    if problems:
        return JobOutcome(
            status="failed",
            error=_job_error(
                "config_error",
                "config rejected: " + "; ".join(problems),
                retryable=False,
                detail={"errors": problems},
            ),
        )

    provider = connector.handlers["metadata"]
    logger.info(
        "job %s: introspecting system=%s mode=%s connector=%s@%s",
        job.job_id, job.config["system"], job.config["mode"],
        manifest.name, manifest.version,
    )
    try:
        result = provider.introspect(job.config)
        if not isinstance(result, IntrospectionResult):
            raise TypeError(
                f"introspect must return IntrospectionResult, got {type(result).__name__}"
            )
        emitted = emit_snapshot(
            manifest=manifest, config=job.config, result=result, captured_at=captured_at
        )
    except QuotaExceeded as exc:
        logger.info("job %s: deferred %ss (%s)", job.job_id, exc.retry_after_s, exc)
        return JobOutcome(
            status="deferred",
            error=_job_error(exc.code, str(exc), retryable=True, detail=dict(exc.detail)),
            retry_after_s=exc.retry_after_s,
        )
    except ConnectorError as exc:
        # scrub the log line too: a driver error can echo the resolved DSN (F3)
        logger.warning("job %s: failed %s (%s)", job.job_id, exc.code, redact_text(str(exc)))
        return _failed(exc)
    except Exception as exc:  # bare crash → `internal` (job spec §6.7)
        logger.warning("job %s: failed internal (%s)", job.job_id, redact_text(repr(exc)))
        return JobOutcome(
            status="failed",
            error=_job_error(
                "internal",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
                detail={"traceback": traceback.format_exc()},
            ),
        )

    logger.info(
        "job %s: emitted %d objects for system=%s",
        job.job_id, len(emitted.document["objects"]), emitted.document["system"],
    )
    return JobOutcome(status="succeeded", snapshot=emitted)


def _run_execute(connector: Connector, job: Job) -> JobOutcome:
    """The `execute` engine (capability §6, job class interactive).

    Two properties differ from the snapshot engine and both are
    deliberate:

    - guardrails are parsed through `Guardrails.parse`, which floors
      rather than trusts. An absent or stripped `guardrails` member
      yields the conservative default, never an unbounded run (CC-3);
    - quota is terminal here, not a deferral (QE-4): the caller is
      blocked awaiting this result, so a `defer` would hang them.
    """
    manifest = connector.manifest
    executor = connector.handlers.get("query")
    if executor is None:
        return JobOutcome(
            status="failed",
            error=_job_error(
                "config_error",
                f"connector {manifest.name!r} does not declare the query capability",
                retryable=False,
            ),
        )
    try:
        request = ExecuteRequest.parse(job.request)
    except ValueError as exc:
        return JobOutcome(
            status="failed",
            error=_job_error("config_error", str(exc), retryable=False),
        )

    guardrails = Guardrails.parse(job.guardrails)
    identity = Identity.parse(job.identity)
    logger.info(
        "job %s: executing dialect=%s system=%s row_cap=%d timeout_s=%d subject=%s",
        job.job_id, request.dialect, job.config.get("system"),
        guardrails.row_cap, guardrails.timeout_s, identity.subject,
    )
    try:
        result = executor.execute(job.config, request, guardrails, identity)
        if not isinstance(result, ExecuteResult):
            raise TypeError(
                f"execute must return ExecuteResult, got {type(result).__name__}"
            )
    except QuotaExceeded as exc:
        # QE-4: interactive quota is a terminal guardrail error carrying
        # the retry-after, never the J-5 deferral batch jobs get.
        logger.info("job %s: quota exhausted (%s)", job.job_id, exc)
        return JobOutcome(
            status="failed",
            error=_job_error(
                "guardrail",
                str(exc),
                retryable=False,
                detail={
                    **dict(exc.detail),
                    "capability_code": "quota_exhausted",
                    "retry_after_s": exc.retry_after_s,
                },
            ),
        )
    except GuardrailViolation as exc:
        logger.info("job %s: guardrail %s (%s)", job.job_id, exc.capability_code, exc)
        return _failed(exc)
    except ConnectorError as exc:
        logger.warning("job %s: failed %s (%s)", job.job_id, exc.code, redact_text(str(exc)))
        return _failed(exc)
    except Exception as exc:
        logger.warning("job %s: failed internal (%s)", job.job_id, redact_text(repr(exc)))
        return JobOutcome(
            status="failed",
            error=_job_error(
                "internal",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
                detail={"traceback": traceback.format_exc()},
            ),
        )

    logger.info(
        "job %s: %d rows (truncated=%s) in %dms",
        job.job_id, result.row_count, result.truncated, result.duration_ms,
    )
    return JobOutcome(status="succeeded", result=result.to_json())


def _run_publish(connector: Connector, job: Job) -> JobOutcome:
    """The `publish` engine (capability §8, job class interactive).

    Same interactive posture as `execute` (quota is terminal, never a
    deferral — the caller is blocked on this result), plus two §8.2
    gates the engine owns so no adapter can forget them:

    - `artifact_version` outside the adapter's declared support fails
      with capability code `artifact_version_unsupported` before the
      adapter parses a byte of the artifact;
    - PB-3: a non-`full` result without `pending_human_steps` is an
      adapter contract bug and fails loudly here rather than shipping a
      journey that quietly overstates what happened.
    """
    manifest = connector.manifest
    publisher = connector.handlers.get("publish")
    if publisher is None:
        return JobOutcome(
            status="failed",
            error=_job_error(
                "config_error",
                f"connector {manifest.name!r} does not declare the publish capability",
                retryable=False,
            ),
        )
    try:
        request = PublishRequest.parse(job.artifact, job.target)
    except ValueError as exc:
        return JobOutcome(
            status="failed",
            error=_job_error("config_error", str(exc), retryable=False),
        )

    supported = getattr(publisher, "SUPPORTED_ARTIFACT_VERSIONS", ("1",))
    if request.artifact_version not in supported:
        return JobOutcome(
            status="failed",
            error=_job_error(
                "config_error",
                f"artifact_version {request.artifact_version!r} unsupported by "
                f"{manifest.name!r} (supports: {', '.join(supported)})",
                retryable=False,
                detail={"capability_code": "artifact_version_unsupported"},
            ),
        )

    identity = Identity.parse(job.identity)
    flags = dict(manifest.capabilities.get("publish", {}))
    logger.info(
        "job %s: publishing artifact=%s target=%s connector=%s@%s subject=%s",
        job.job_id, request.artifact.get("id"), request.target,
        manifest.name, manifest.version, identity.subject,
    )
    try:
        result = publisher.publish(job.config, request, identity, flags)
        if not isinstance(result, PublishResult):
            raise TypeError(
                f"publish must return PublishResult, got {type(result).__name__}"
            )
    except QuotaExceeded as exc:
        logger.info("job %s: quota exhausted (%s)", job.job_id, exc)
        return JobOutcome(
            status="failed",
            error=_job_error(
                "guardrail",
                str(exc),
                retryable=False,
                detail={
                    **dict(exc.detail),
                    "capability_code": "quota_exhausted",
                    "retry_after_s": exc.retry_after_s,
                },
            ),
        )
    except ConnectorError as exc:
        logger.warning("job %s: failed %s (%s)", job.job_id, exc.code, redact_text(str(exc)))
        return _failed(exc)
    except Exception as exc:
        logger.warning("job %s: failed internal (%s)", job.job_id, redact_text(repr(exc)))
        return JobOutcome(
            status="failed",
            error=_job_error(
                "internal",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
                detail={"traceback": traceback.format_exc()},
            ),
        )

    if result.mode != "full" and not result.pending_human_steps:
        return JobOutcome(
            status="failed",
            error=_job_error(
                "internal",
                f"adapter returned mode={result.mode!r} without pending_human_steps "
                "(PB-3: mandatory whenever mode is not 'full')",
                retryable=False,
            ),
        )

    logger.info(
        "job %s: published mode=%s created=%d pending_steps=%d",
        job.job_id, result.mode, len(result.created), len(result.pending_human_steps),
    )
    return JobOutcome(status="succeeded", result=result.to_json())
