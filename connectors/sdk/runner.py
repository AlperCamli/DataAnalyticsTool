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
from connectors.sdk.errors import ConnectorError, QuotaExceeded
from connectors.sdk.providers import IntrospectionResult

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


def _failed(exc: ConnectorError) -> JobOutcome:
    return JobOutcome(
        status="failed",
        error=JobError(exc.code, str(exc), exc.retryable, dict(exc.detail)),
    )


def run_job(connector: Connector, job: Job, *, captured_at: str | None = None) -> JobOutcome:
    """Execute one job. Only job type `snapshot` has an engine so far."""
    if job.type != "snapshot":
        raise ValueError(f"no engine for job type {job.type!r} in this SDK version")

    manifest = connector.manifest
    if "metadata" not in connector.handlers:
        return JobOutcome(
            status="failed",
            error=JobError(
                "config_error",
                f"connector {manifest.name!r} does not declare the metadata capability",
                retryable=False,
            ),
        )
    problems = config_problems(manifest, job.config)
    if problems:
        return JobOutcome(
            status="failed",
            error=JobError(
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
            error=JobError(exc.code, str(exc), retryable=True, detail=dict(exc.detail)),
            retry_after_s=exc.retry_after_s,
        )
    except ConnectorError as exc:
        logger.warning("job %s: failed %s (%s)", job.job_id, exc.code, exc)
        return _failed(exc)
    except Exception as exc:  # bare crash → `internal` (job spec §6.7)
        logger.warning("job %s: failed internal (%r)", job.job_id, exc)
        return JobOutcome(
            status="failed",
            error=JobError(
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
