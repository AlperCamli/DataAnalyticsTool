"""Job-protocol runner daemon (job spec §3) — CP-3a ruling D1.

    python -m connectors.sdk.service --config runner.yaml [--once] [-v]

A thin, long-running transport around the existing `run_job` engine: it
declares its hosted `(connector, version)` pairs, long-poll claims over
HTTPS with a per-runner bearer token, heartbeats while the engine works,
resolves credential references (J-4) through the vault seam, and maps
the engine's `JobOutcome` onto the terminal wire calls — connectors run
completely unchanged.

Config (YAML):

    core_url: http://localhost:8080
    token_env: CL_RUNNER_TOKEN     # or `token:` inline (discouraged)
    runner_id: runner-a1           # default: cl-<hostname>-<pid>
    connectors:                    # MODULE:ATTR, as in the local CLI
      - connectors.postgres.connector:connector
    classes: [batch, interactive]  # interactive = execute/publish lane
    wait_s: 25
    resolver: { kind: vault }                  # or process-env / env-file + path:
    execution_preflight:           # G3 gate; see below
      - connector: postgres
        config: { system: supabase, execute_dsn_env: CL_EXEC_DSN }

Credential injection: each payload credential `{ref, key}` resolves to a
value held in a job-scoped environment variable; the connector receives
only the *variable name* through its declared `*_env` config field
(postgres `dsn_env` and `execute_dsn_env`, ga4/gsc `credentials_env`), so
connector code and config schemas stay exactly as shipped. Resolved
values are scrubbed from any outgoing error detail as defense in depth
(§7/JC-8).

Execution preflight (CP-6 ruling G3): before offering to claim `execute`
jobs, the runner asks each configured connector's QueryExecutor to prove
its execution role cannot write. A connector that fails has `execute`
**withheld from its claim declaration** — it never offers to do the work
— while its metadata capability keeps running. Failing open here would
mean serving governed execution against a role that can write, which is
the one outcome the check exists to prevent.

Cancellation (§6.3/JC-7): the heartbeat response's `cancel_requested`
stops the runner within one heartbeat interval — the work thread is
abandoned (introspection is read-only and idempotent per J-7) and the
job is failed with code `cancelled`. A lost lease (409) likewise
abandons the work; the core has already made the job re-claimable.
"""

import argparse
import json
import logging
import os
import socket
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from connectors.sdk.connector import Connector
from connectors.sdk.local import load_connector
from connectors.sdk.manifest import CAPABILITY_JOB_TYPES
from connectors.sdk.protocol import (
    DeliveryRejected,
    JobApiClient,
    LeaseLost,
    ProtocolError,
)
from connectors.sdk.runner import Job, JobOutcome, run_job
from connectors.sdk.redact import redact_text
from connectors.sdk.vault import (
    ENV_SCHEME,
    VAULT_SCHEME,
    CredentialResolver,
    EnvResolver,
    SchemeRouter,
    VaultResolutionError,
    VaultResolver,
)

logger = logging.getLogger("connectors.sdk.service")

# Manifest credential key → the connector's declared env-indirection
# config field. Extending this map is how a new credential kind joins the
# runner; connectors themselves never change.
CREDENTIAL_CONFIG_KEYS: dict[str, str] = {
    "dsn": "dsn_env",
    "execute_dsn": "execute_dsn_env",
    "service_account": "credentials_env",
    "client_secret": "client_secret_env",
}

# Job types this SDK can execute (run_job dispatches by type).
EXECUTABLE_TYPES = ("snapshot", "execute", "publish", "test_connection")

# `test_connection` is the one job type that maps to no single
# capability: the builtin probe (capability §3 `health_probe: builtin`)
# runs across whichever capabilities the connector declares. A connector
# opts in by declaring `health_probe: builtin` in its manifest.
PROBE_TYPE = "test_connection"


class RunnerConfigError(Exception):
    pass


@dataclass(frozen=True)
class RunnerConfig:
    core_url: str
    token: str
    runner_id: str
    connector_specs: tuple[str, ...]
    classes: tuple[str, ...] = ("batch",)
    wait_s: int = 25
    claim_backoff_s: float = 3.0
    heartbeat_interval_s: float | None = None  # default: lease ttl / 2
    resolver_kind: str = "process-env"
    resolver_path: str | None = None
    #: `vault` only: keep resolving `env://` references alongside
    #: `vault://` ones. True during A-4's migration, because references
    #: flip one connection at a time; set false once the estate is
    #: migrated and a surviving plaintext reference should be an error
    #: rather than a warning.
    resolver_allow_env: bool = True
    # G3 startup gate: per-connector execution configs to preflight
    # before this runner offers to claim `execute` jobs.
    execution_preflight: tuple[dict, ...] = ()


def load_runner_config(path: str | Path) -> RunnerConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RunnerConfigError(f"cannot read runner config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RunnerConfigError(f"runner config {path}: top level must be a mapping")

    token = raw.get("token")
    token_env = raw.get("token_env")
    if token_env:
        token = os.environ.get(token_env)
        if not token:
            raise RunnerConfigError(
                f"runner config {path}: token_env {token_env!r} is not set"
            )
    if not token:
        raise RunnerConfigError(f"runner config {path}: token or token_env required")

    specs = raw.get("connectors")
    if not isinstance(specs, list) or not specs or not all(
        isinstance(s, str) and s for s in specs
    ):
        raise RunnerConfigError(
            f"runner config {path}: connectors must be a non-empty list of MODULE:ATTR"
        )

    resolver = raw.get("resolver") or {"kind": "process-env"}
    kind = resolver.get("kind", "process-env")
    if kind not in ("process-env", "env-file", "vault"):
        raise RunnerConfigError(
            f"runner config {path}: resolver.kind must be process-env, env-file or vault"
        )
    if kind == "env-file" and not resolver.get("path"):
        raise RunnerConfigError(f"runner config {path}: env-file resolver needs path")
    allow_env = resolver.get("allow_env", True)
    if not isinstance(allow_env, bool):
        raise RunnerConfigError(f"runner config {path}: resolver.allow_env must be a boolean")

    if not raw.get("core_url"):
        raise RunnerConfigError(f"runner config {path}: core_url required")

    return RunnerConfig(
        core_url=raw["core_url"],
        token=token,
        runner_id=raw.get("runner_id") or f"cl-{socket.gethostname()}-{os.getpid()}",
        connector_specs=tuple(specs),
        classes=tuple(raw.get("classes") or ("batch",)),
        wait_s=int(raw.get("wait_s", 25)),
        claim_backoff_s=float(raw.get("claim_backoff_s", 3.0)),
        heartbeat_interval_s=(
            float(raw["heartbeat_interval_s"]) if raw.get("heartbeat_interval_s") else None
        ),
        resolver_kind=kind,
        resolver_path=resolver.get("path"),
        resolver_allow_env=allow_env,
        execution_preflight=tuple(raw.get("execution_preflight") or ()),
    )


def make_resolver(config: RunnerConfig) -> CredentialResolver:
    """Build the credential resolver this runner will use (J-4).

    `vault` is the supported production kind; the two env kinds are the
    pilot-only local-dev backend (ruling D1, and see vault.py's module
    docstring). Under `vault`, `env://` stays resolvable by default so
    A-4's migration can flip references one connection at a time — set
    `resolver.allow_env: false` when the estate is migrated and a
    surviving plaintext reference should fail loudly.
    """
    if config.resolver_kind == "vault":
        backends: dict[str, CredentialResolver] = {
            VAULT_SCHEME: VaultResolver.from_env(),
        }
        if config.resolver_allow_env:
            backends[ENV_SCHEME] = EnvResolver.from_process_env()
        return SchemeRouter(backends)
    if config.resolver_kind == "env-file":
        return EnvResolver.from_env_file(config.resolver_path)
    return EnvResolver.from_process_env()


def scrub_secrets(value: object, secrets: list[str]) -> object:
    """Replace any resolved secret occurring anywhere in a JSON-ish value."""
    if not secrets:
        return value
    text = json.dumps(value)
    for secret in secrets:
        if secret:
            text = text.replace(json.dumps(secret)[1:-1], "[REDACTED]")
    return json.loads(text)


class _HeartbeatLoop(threading.Thread):
    """Beats every `interval_s`, tracks lease rotation, surfaces
    cancellation and lease loss as events (§6.3)."""

    def __init__(self, client: JobApiClient, job_id: str, lease_token: str,
                 interval_s: float):
        super().__init__(daemon=True, name=f"heartbeat-{job_id}")
        self._client = client
        self._job_id = job_id
        self._interval_s = interval_s
        self._lock = threading.Lock()
        self._token = lease_token
        self._stop = threading.Event()
        self.cancelled = threading.Event()
        self.lost = threading.Event()

    @property
    def token(self) -> str:
        with self._lock:
            return self._token

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self._interval_s):
            try:
                response = self._client.heartbeat(
                    self._job_id, self.token, progress={"phase": "running"}
                )
            except LeaseLost:
                self.lost.set()
                return
            except ProtocolError as exc:
                # Transient — the lease outlives one missed beat (§5).
                logger.warning("job %s: heartbeat error (%s)", self._job_id, exc)
                continue
            lease = response.get("lease") or {}
            if isinstance(lease.get("token"), str):
                with self._lock:
                    self._token = lease["token"]
            if response.get("cancel_requested"):
                self.cancelled.set()
                return


@dataclass
class Runner:
    config: RunnerConfig
    client: JobApiClient = None  # type: ignore[assignment]
    connectors: dict[str, Connector] = field(default_factory=dict)
    resolver: CredentialResolver = None  # type: ignore[assignment]
    # connector name -> why execution is refused (G3 preflight).
    execution_refused: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.client is None:
            self.client = JobApiClient(self.config.core_url, self.config.token)
        if self.resolver is None:
            self.resolver = make_resolver(self.config)
        if not self.connectors:
            for spec in self.config.connector_specs:
                connector = load_connector(spec)
                self.connectors[connector.manifest.name] = connector

    # -- claim declaration -------------------------------------------------

    def declared_connectors(self) -> list[dict]:
        """§6.1 declaration, plus the additive per-connector `types` field
        (the job types this runner can actually execute for it).

        A connector whose execution preflight failed (G3) has `execute`
        withheld here: the runner does not merely reject execute jobs, it
        never offers to claim them.
        """
        declared = []
        for connector in self.connectors.values():
            manifest = connector.manifest
            types = sorted(
                CAPABILITY_JOB_TYPES[cap]
                for cap in manifest.capabilities
                if CAPABILITY_JOB_TYPES.get(cap) in EXECUTABLE_TYPES
            )
            if manifest.name in self.execution_refused:
                types = [t for t in types if t != "execute"]
            if manifest.health_probe == "builtin":
                types = sorted({*types, PROBE_TYPE})
            declared.append(
                {"name": manifest.name, "version": manifest.version, "types": types}
            )
        return declared

    # -- G3 execution preflight ---------------------------------------------

    def preflight_execution(self) -> dict[str, str]:
        """Run each configured execution preflight before serving.

        A connector that cannot prove its execution role is read-only is
        recorded in `execution_refused` and will not claim `execute`
        jobs. The failure is loud and names the reason: silently serving
        execution against a role that can write is the exact outcome the
        check exists to prevent, so "fail open" is not an option here.
        """
        refused: dict[str, str] = {}
        for entry in self.config.execution_preflight:
            name = entry.get("connector")
            config = dict(entry.get("config") or {})
            connector = self.connectors.get(name)
            if connector is None:
                refused[name] = f"connector {name!r} is not hosted by this runner"
                logger.error("execution preflight: %s", refused[name])
                continue
            executor = connector.handlers.get("query")
            if executor is None:
                refused[name] = f"connector {name!r} declares no query capability"
                logger.error("execution preflight: %s", refused[name])
                continue
            try:
                facts = executor.preflight(config)
            except Exception as exc:
                reason = redact_text(str(exc))
                refused[name] = reason
                logger.error(
                    "execution preflight FAILED for %s: %s — this runner will NOT serve "
                    "execution for it", name, reason,
                )
                continue
            logger.info("execution preflight passed for %s: %s", name, facts)
        self.execution_refused = refused
        return refused

    # -- credential handling (J-4) ------------------------------------------

    def _inject_credentials(
        self, job_record: dict, config: dict
    ) -> tuple[list[str], list[str]]:
        """Resolve payload credential refs into job-scoped env vars; returns
        (env var names to clean up, resolved values for scrubbing)."""
        env_names: list[str] = []
        secrets: list[str] = []
        for entry in job_record.get("payload", {}).get("credentials") or []:
            ref, key = entry.get("ref"), entry.get("key")
            if not ref or not key:
                raise VaultResolutionError(
                    "credential entry must carry both 'ref' and 'key'"
                )
            config_key = CREDENTIAL_CONFIG_KEYS.get(key)
            if config_key is None:
                raise VaultResolutionError(
                    f"credential key {key!r} unknown to this runner "
                    f"(known: {sorted(CREDENTIAL_CONFIG_KEYS)})"
                )
            value = self.resolver.resolve(ref)
            var = f"CL_CRED_{uuid.uuid4().hex}_{key.upper()}"
            os.environ[var] = value
            env_names.append(var)
            secrets.append(value)
            config[config_key] = var
        return env_names, secrets

    # -- job execution -------------------------------------------------------

    def _fail(self, job_id: str, lease_token: str, error: dict,
              secrets: list[str]) -> None:
        try:
            self.client.fail(job_id, lease_token, scrub_secrets(error, secrets))
        except (LeaseLost, ProtocolError) as exc:
            logger.warning("job %s: fail call not delivered (%s)", job_id, exc)

    def execute(self, job_record: dict) -> None:
        job_id = job_record["job_id"]
        lease_token = job_record["lease"]["token"]
        name = job_record.get("connector", {}).get("name")
        connector = self.connectors.get(name)
        job_type = job_record.get("type")

        if job_type == "execute" and name in self.execution_refused:
            # G3: claimed anyway (a stale declaration, or another runner's
            # job) — refuse with the reason rather than executing.
            self._fail(job_id, lease_token, {
                "code": "config_error",
                "message": f"this runner refuses to serve execution for {name!r}: "
                           f"{self.execution_refused[name]}",
                "retryable": False,
            }, [])
            return

        if connector is None or job_type not in EXECUTABLE_TYPES:
            self._fail(job_id, lease_token, {
                "code": "config_error",
                "message": f"runner {self.config.runner_id} cannot execute "
                           f"type={job_type!r} connector={name!r}",
                "retryable": False,
            }, [])
            return

        payload = job_record.get("payload", {}) or {}
        config = dict(payload.get("config") or {})
        env_names: list[str] = []
        secrets: list[str] = []
        try:
            try:
                env_names, secrets = self._inject_credentials(job_record, config)
            except VaultResolutionError as exc:
                # §7: vault-stage auth_error — never started.
                try:
                    self.client.start(job_id, lease_token)
                except (LeaseLost, ProtocolError):
                    return
                self._fail(job_id, lease_token, {
                    "code": exc.code, "message": str(exc),
                    "retryable": exc.retryable, "detail": dict(exc.detail),
                }, secrets)
                return

            try:
                started = self.client.start(job_id, lease_token)
            except LeaseLost:
                logger.info("job %s: lease lost before start; abandoning", job_id)
                return
            except ProtocolError as exc:
                logger.warning("job %s: start failed (%s); abandoning", job_id, exc)
                return
            if started.get("cancel_requested"):
                self._fail(job_id, lease_token, _CANCELLED_ERROR, secrets)
                return

            interval = self.config.heartbeat_interval_s or _default_interval(job_record)
            heartbeat = _HeartbeatLoop(self.client, job_id, lease_token, interval)
            heartbeat.start()

            outcome_box: list[JobOutcome] = []
            worker = threading.Thread(
                target=lambda: outcome_box.append(
                    run_job(connector, Job(
                        job_id=job_id, config=config, type=job_type,
                        credentials=tuple(
                            job_record.get("payload", {}).get("credentials") or ()
                        ),
                        # Interactive `execute` members (capability §6);
                        # absent on snapshot jobs and ignored there.
                        request=payload.get("request"),
                        guardrails=payload.get("guardrails"),
                        identity=payload.get("identity"),
                        # Interactive `publish` members (capability §8.2).
                        artifact=payload.get("artifact"),
                        target=payload.get("target"),
                        # Two-call contract members (§8.2 amendment).
                        mode=payload.get("mode"),
                        results=payload.get("results"),
                        previous=payload.get("previous"),
                        attestation=payload.get("attestation"),
                    ))
                ),
                daemon=True, name=f"work-{job_id}",
            )
            worker.start()
            try:
                while worker.is_alive():
                    worker.join(timeout=0.1)
                    if heartbeat.lost.is_set():
                        logger.info("job %s: lease lost; abandoning work", job_id)
                        return
                    if heartbeat.cancelled.is_set():
                        logger.info("job %s: cancel requested; stopping", job_id)
                        self._fail(job_id, heartbeat.token, _CANCELLED_ERROR, secrets)
                        return
            finally:
                heartbeat.stop()
            if heartbeat.lost.is_set():
                return
            if heartbeat.cancelled.is_set():
                self._fail(job_id, heartbeat.token, _CANCELLED_ERROR, secrets)
                return
            self._deliver(job_id, heartbeat.token, outcome_box, secrets)
        except Exception as exc:  # job-level isolation (QE-6, job §6.7)
            # Anything unexpected on the runner side of a job — a result
            # value the serializer cannot encode, a bug in this harness —
            # is that job's failure, not the runner's death. Before D-85 a
            # `date` in a result took the process down and every queued job
            # after it hung to lease expiry. The type name is enough for
            # triage; the value never enters the message (JC-8).
            logger.exception("job %s: unhandled runner-side error", job_id)
            self._fail(job_id, lease_token, {
                "code": "internal",
                "message": f"runner-side failure handling the job ({type(exc).__name__})",
                "retryable": True,
            }, secrets)
        finally:
            for var in env_names:
                os.environ.pop(var, None)

    def _deliver(self, job_id: str, lease_token: str,
                 outcome_box: list[JobOutcome], secrets: list[str]) -> None:
        if not outcome_box:  # worker died without producing an outcome
            self._fail(job_id, lease_token, {
                "code": "internal",
                "message": "connector worker produced no outcome",
                "retryable": True,
            }, secrets)
            return
        outcome = outcome_box[0]
        if outcome.status == "succeeded":
            try:
                if outcome.snapshot is not None:
                    self.client.complete_snapshot(
                        job_id, lease_token, outcome.snapshot.serialized
                    )
                    logger.info("job %s: delivered snapshot", job_id)
                else:
                    # Interactive capability result (§6.4): relayed to the
                    # blocked producer, not stored as a snapshot.
                    self.client.complete(
                        job_id, lease_token, scrub_secrets(outcome.result, secrets)
                    )
                    logger.info("job %s: delivered result", job_id)
            except DeliveryRejected as exc:
                # JC-6: 422 is final — the core has dead-lettered the job.
                logger.error("job %s: delivery rejected by core (%s)", job_id, exc)
            except LeaseLost:
                logger.info("job %s: lease lost at delivery; abandoning", job_id)
            except ProtocolError as exc:
                logger.warning("job %s: delivery failed (%s)", job_id, exc)
        elif outcome.status == "deferred":
            try:
                self.client.defer(job_id, lease_token, outcome.retry_after_s, {
                    "code": outcome.error.code,
                    "message": str(scrub_secrets(outcome.error.message, secrets)),
                })
                logger.info("job %s: deferred %ss", job_id, outcome.retry_after_s)
            except (LeaseLost, ProtocolError) as exc:
                logger.warning("job %s: defer not delivered (%s)", job_id, exc)
        else:
            error = outcome.error
            self._fail(job_id, lease_token, {
                "code": error.code, "message": error.message,
                "retryable": error.retryable, "detail": dict(error.detail),
            }, secrets)
            logger.info("job %s: failed %s", job_id, error.code)

    # -- main loop -----------------------------------------------------------

    def run_forever(self, *, once: bool = False, max_jobs: int | None = None) -> int:
        executed = 0
        self.preflight_execution()
        declared = self.declared_connectors()
        logger.info(
            "runner %s: hosting %s against %s",
            self.config.runner_id,
            ", ".join(f"{d['name']}@{d['version']}" for d in declared),
            self.config.core_url,
        )
        while True:
            try:
                job = self.client.claim(
                    runner_id=self.config.runner_id,
                    connectors=declared,
                    classes=list(self.config.classes),
                    wait_s=self.config.wait_s,
                )
            except ProtocolError as exc:
                logger.warning("claim failed (%s); backing off", exc)
                self._sleep(self.config.claim_backoff_s)
                continue
            if job is None:
                continue
            logger.info(
                "job %s: claimed type=%s system=%s connector=%s",
                job.get("job_id"), job.get("type"), job.get("system"),
                job.get("connector", {}).get("name"),
            )
            try:
                self.execute(job)
            except Exception:  # last line of the same defence
                logger.exception(
                    "job %s: failure escaped job handling; runner continues",
                    job.get("job_id"),
                )
            executed += 1
            if once or (max_jobs is not None and executed >= max_jobs):
                return executed

    @staticmethod
    def _sleep(seconds: float) -> None:
        threading.Event().wait(seconds)


_CANCELLED_ERROR = {
    "code": "cancelled",
    "message": "cancelled by producer request",
    "retryable": False,
}


def _default_interval(job_record: dict) -> float:
    ttl = job_record.get("lease", {}).get("ttl_s")
    if isinstance(ttl, (int, float)) and ttl > 0:
        return max(ttl / 2.0, 0.5)
    return 30.0  # lease_ttl_s default 60 (§5) → beat at ttl/2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m connectors.sdk.service",
        description="Run the job-protocol runner daemon.",
    )
    parser.add_argument("--config", required=True, metavar="FILE",
                        help="runner config YAML")
    parser.add_argument("--once", action="store_true",
                        help="execute exactly one job, then exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        config = load_runner_config(args.config)
    except RunnerConfigError as exc:
        print(str(exc), flush=True)
        return 2
    runner = Runner(config)
    try:
        runner.run_forever(once=args.once)
    except KeyboardInterrupt:
        logger.info("runner %s: interrupted", config.runner_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
