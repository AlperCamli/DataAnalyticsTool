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
