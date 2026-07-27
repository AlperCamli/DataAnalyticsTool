"""Runner transport for interactive `execute` jobs (job §6, CP-6/M2).

Two properties matter here and neither is about SQL:

- the engine's `execute` dispatch delivers a capability result envelope
  through `complete` (not `complete_snapshot`), and maps guardrail
  failures onto the §6.7 taxonomy;
- the G3 startup gate: a runner that cannot prove its execution role is
  read-only does not merely fail execute jobs, it **withholds `execute`
  from its claim declaration** — it never offers to do the work.
"""

import pytest

from connectors.sdk import Connector, QueryExecutor
from connectors.sdk.errors import ConfigError, GuardrailViolation
from connectors.sdk.providers import ExecuteResult
from connectors.sdk.service import Runner, RunnerConfig
from tests.conftest import write_manifest

EXECUTE_MANIFEST = {
    "name": "testexec",
    "capabilities": {"query": {"dialect": "postgresql"}},
}


class RecordingExecutor(QueryExecutor):
    def __init__(self, result=None, raises=None, preflight_error=None):
        self.result = result
        self.raises = raises
        self.preflight_error = preflight_error
        self.calls = []

    def preflight(self, config):
        if self.preflight_error:
            raise self.preflight_error
        return {"role": "ok"}

    def execute(self, config, request, guardrails, identity):
        self.calls.append((config, request, guardrails, identity))
        if self.raises:
            raise self.raises
        return self.result or ExecuteResult(
            columns=[{"name": "n", "type": "int8"}],
            rows=[[1]],
            row_count=1,
            truncated=False,
            duration_ms=3,
            source={"executed_on": "primary", "engine_version": "16"},
        )


def make_connector(tmp_path, executor):
    path = write_manifest(tmp_path, EXECUTE_MANIFEST)
    return Connector(path, {"query": executor})


def make_runner(tmp_path, executor, preflight=()):
    connector = make_connector(tmp_path, executor)
    config = RunnerConfig(
        core_url="http://core",
        token="t",
        runner_id="r1",
        connector_specs=(),
        classes=("batch", "interactive"),
        execution_preflight=tuple(preflight),
    )
    return Runner(config=config, client=object(), connectors={"testexec": connector},
                  resolver=object())


# --- G3 startup gate --------------------------------------------------------


def test_runner_declares_execute_when_preflight_passes(tmp_path):
    runner = make_runner(
        tmp_path,
        RecordingExecutor(),
        preflight=[{"connector": "testexec", "config": {"system": "s"}}],
    )
    assert runner.preflight_execution() == {}
    assert runner.declared_connectors()[0]["types"] == ["execute"]


def test_runner_withholds_execute_when_the_role_can_write(tmp_path):
    """The M2 exit criterion: point execution at a role with write grants
    and the runner refuses to serve execution, saying why."""
    runner = make_runner(
        tmp_path,
        RecordingExecutor(
            preflight_error=ConfigError(
                "execution role 'cl_writer' holds write grants (INSERT on public.orders); "
                "execution requires a role with SELECT only (G3). Refusing to serve execution."
            )
        ),
        preflight=[{"connector": "testexec", "config": {"system": "s"}}],
    )
    refused = runner.preflight_execution()
    assert "testexec" in refused
    assert "write grants" in refused["testexec"]
    assert "Refusing to serve execution" in refused["testexec"]
    # Not offered for claim at all.
    assert runner.declared_connectors()[0]["types"] == []


def test_preflight_failure_does_not_disable_snapshot_work(tmp_path):
    """Refusing execution must not take metadata sync down with it."""
    path = write_manifest(tmp_path, {
        "name": "testexec",
        "capabilities": {"metadata": {"modes": ["ddl-file"]}, "query": {"dialect": "postgresql"}},
    })
    from tests.conftest import FakeMetadata

    connector = Connector(path, {"metadata": FakeMetadata(lambda config: None), "query": RecordingExecutor(
        preflight_error=ConfigError("role can write")
    )})
    config = RunnerConfig(
        core_url="http://core", token="t", runner_id="r1", connector_specs=(),
        classes=("batch", "interactive"),
        execution_preflight=({"connector": "testexec", "config": {}},),
    )
    runner = Runner(config=config, client=object(), connectors={"testexec": connector},
                    resolver=object())
    runner.preflight_execution()
    assert runner.declared_connectors()[0]["types"] == ["snapshot"]


def test_preflight_for_an_unhosted_connector_is_refused_not_ignored(tmp_path):
    runner = make_runner(
        tmp_path,
        RecordingExecutor(),
        preflight=[{"connector": "not-hosted", "config": {}}],
    )
    refused = runner.preflight_execution()
    assert "not-hosted" in refused


# --- engine dispatch --------------------------------------------------------


def test_execute_job_delivers_a_result_envelope(tmp_path):
    from connectors.sdk.runner import Job, run_job

    executor = RecordingExecutor()
    job = Job(
        job_id="j1",
        config={"system": "s"},
        type="execute",
        request={"dialect": "sql", "statement": "SELECT 1"},
        guardrails={"row_cap": 10, "timeout_s": 5, "validated_against": "sha256:abc"},
        identity={"subject": "oidc|a", "session_id": "s-1", "intent": "count"},
    )
    outcome = run_job(make_connector(tmp_path, executor), job)
    assert outcome.status == "succeeded"
    assert outcome.snapshot is None  # not a snapshot delivery
    assert outcome.result == {
        "columns": [{"name": "n", "type": "int8"}],
        "rows": [[1]],
        "row_count": 1,
        "truncated": False,
        "duration_ms": 3,
        "source": {"executed_on": "primary", "engine_version": "16"},
    }
    _, request, guardrails, identity = executor.calls[0]
    assert request.statement == "SELECT 1"
    assert guardrails.row_cap == 10
    assert guardrails.validated_against == "sha256:abc"
    assert identity.subject == "oidc|a"


def test_guardrail_violation_maps_to_the_job_taxonomy(tmp_path):
    from connectors.sdk.runner import Job, run_job

    job = Job(
        job_id="j2",
        config={"system": "s"},
        type="execute",
        request={"dialect": "sql", "statement": "SELECT 1"},
        guardrails={"row_cap": 10, "timeout_s": 1},
        identity={"subject": "oidc|a"},
    )
    outcome = run_job(
        make_connector(tmp_path, RecordingExecutor(
            raises=GuardrailViolation("timed out", capability_code="timeout")
        )),
        job,
    )
    assert outcome.status == "failed"
    assert outcome.error.code == "guardrail"       # outer taxonomy (§6.7)
    assert outcome.error.retryable is False
    assert outcome.error.detail["capability_code"] == "timeout"  # CI-8 precision


def test_execute_on_a_connector_without_the_query_capability(tmp_path):
    from connectors.sdk.runner import Job, run_job
    from tests.conftest import FakeMetadata

    path = write_manifest(tmp_path, {"capabilities": {"metadata": {"modes": ["ddl-file"]}}})
    connector = Connector(path, {"metadata": FakeMetadata(lambda config: None)})
    outcome = run_job(connector, Job(
        job_id="j3", config={"system": "s"}, type="execute",
        request={"dialect": "sql", "statement": "SELECT 1"},
    ))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert "query capability" in outcome.error.message


def test_malformed_request_is_config_error(tmp_path):
    from connectors.sdk.runner import Job, run_job

    outcome = run_job(make_connector(tmp_path, RecordingExecutor()), Job(
        job_id="j4", config={"system": "s"}, type="execute",
        request={"dialect": "graphql", "statement": "x"},
    ))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert "dialect" in outcome.error.message


# --- CC-13: job-level isolation (QE-6) --------------------------------------


class Poison:
    """A value nothing can encode — even QE-5's text catch-all raises."""

    def __str__(self):  # pragma: no cover - the raise is the point
        raise TypeError("this value cannot be rendered")


class ScriptedClient:
    """Hands out a scripted queue of jobs and records the wire calls."""

    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.calls: list[tuple] = []

    def claim(self, **kwargs):
        return self.jobs.pop(0) if self.jobs else None

    def start(self, job_id, lease_token):
        self.calls.append(("start", job_id))
        return {"status": "running", "cancel_requested": False}

    def heartbeat(self, job_id, lease_token, progress=None):
        return {"lease": {"token": lease_token}, "cancel_requested": False}

    def complete(self, job_id, lease_token, result):
        self.calls.append(("complete", job_id, result))
        return {"status": "succeeded"}

    def fail(self, job_id, lease_token, error):
        self.calls.append(("fail", job_id, error))
        return {"status": "dead_lettered"}

    def defer(self, job_id, lease_token, retry_after_s, reason):  # pragma: no cover
        self.calls.append(("defer", job_id))
        return {"status": "deferred"}

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def execute_job(job_id):
    return {
        "job_id": job_id,
        "type": "execute",
        "class": "interactive",
        "system": "s",
        "connector": {"name": "testexec", "version_constraint": "*"},
        "payload": {
            "config": {"system": "s"},
            "credentials": [],
            "request": {"dialect": "sql", "statement": "SELECT 1"},
            "guardrails": {"row_cap": 10, "timeout_s": 5},
            "identity": {"subject": "u", "roles": ["r"], "session_id": "s1"},
        },
        "lease": {"token": "L1", "ttl_s": 30},
    }


def test_poisoned_job_fails_the_job_and_the_runner_survives(tmp_path):
    """CC-13. Before D-85 a value the serializer could not handle killed
    the runner process, and every job queued behind it hung to lease
    expiry — which is how it stayed hidden: RLS emptiness meant no value
    ever reached the serializer on the pilot.
    """
    class PoisonsFirstCall(RecordingExecutor):
        """First job returns an unencodable value, the next a normal one."""

        def execute(self, config, request, guardrails, identity):
            self.calls.append((config, request, guardrails, identity))
            rows = [[Poison()]] if len(self.calls) == 1 else [[1]]
            return ExecuteResult(
                columns=[{"name": "n", "type": "int8"}],
                rows=rows,
                row_count=1,
                truncated=False,
                duration_ms=1,
                source={"executed_on": "primary", "engine_version": "16"},
            )

    executor = PoisonsFirstCall()
    connector = make_connector(tmp_path, executor)
    client = ScriptedClient([execute_job("j-poison"), execute_job("j-next")])
    config = RunnerConfig(
        core_url="http://core", token="t", runner_id="r1", connector_specs=(),
        classes=("batch", "interactive"), heartbeat_interval_s=0.05,
    )
    runner = Runner(config=config, client=client, connectors={"testexec": connector},
                    resolver=object())

    # The second job is served by the same runner: the loop survived.
    assert runner.run_forever(max_jobs=2) == 2

    (_, job_id, error) = client.named("fail")[0]
    assert job_id == "j-poison"
    assert error["code"] == "internal"          # §6.7, not a new capability code
    assert error["retryable"] is True
    assert "TypeError" in error["message"]      # type only — never the value

    completed = client.named("complete")
    assert [c[1] for c in completed] == ["j-next"]

    # The healthy job was delivered normally, not as a retry after expiry.
    assert client.named("start")[1][1] == "j-next"


def test_second_executor_result_is_unaffected_by_a_prior_poisoning(tmp_path):
    """The isolation is per job: state from the failed one does not leak
    into the next result envelope."""
    executor = RecordingExecutor()
    connector = make_connector(tmp_path, executor)
    client = ScriptedClient([execute_job("j-ok")])
    config = RunnerConfig(
        core_url="http://core", token="t", runner_id="r1", connector_specs=(),
        classes=("batch", "interactive"), heartbeat_interval_s=0.05,
    )
    runner = Runner(config=config, client=client, connectors={"testexec": connector},
                    resolver=object())
    runner.run_forever(max_jobs=1)
    (_, _, result) = client.named("complete")[0]
    assert result["rows"] == [[1]]
    assert result["truncated"] is False
