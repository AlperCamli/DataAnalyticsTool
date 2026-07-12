"""Postgres connector config gate and failure paths (no Docker needed).

MP-1/CC-2: the requested mode is never satisfied another way, and a
failed job emits nothing (S-6's connector half; the transport half is
test_sdk_runner's C-7 coverage on the demo connector).
"""

import pytest

from connectors.postgres.connector import connector
from connectors.sdk.emission import config_problems
from connectors.sdk.runner import Job, run_job


def cfg(**kw) -> dict:
    return {"system": "demo", **kw}


def test_manifest_declares_both_modes():
    assert connector.manifest.metadata_modes() == ("ddl-file", "live")


def test_ddl_mode_requires_files_and_image():
    problems = config_problems(connector.manifest, cfg(mode="ddl-file"))
    assert any("ddl_files" in p for p in problems)
    # `image` is required with no default: the image major must match the
    # live target's major or the ddl→live switch manufactures spurious
    # breaking diffs (D-20)
    problems = config_problems(connector.manifest, cfg(mode="ddl-file", ddl_files=["x.sql"]))
    assert any("image" in p for p in problems)


def test_live_mode_requires_dsn_or_dsn_env():
    assert config_problems(connector.manifest, cfg(mode="live")) != []
    assert config_problems(connector.manifest, cfg(mode="live", dsn="postgresql://u@h/db")) == []
    assert config_problems(connector.manifest, cfg(mode="live", dsn_env="PG_DSN")) == []


def test_unknown_config_keys_rejected():
    problems = config_problems(connector.manifest, cfg(mode="live", dsn="x", nope=1))
    assert problems != []


def test_undeclared_mode_rejected():
    problems = config_problems(connector.manifest, cfg(mode="api", dsn="x"))
    assert problems != []


def test_live_unreachable_dsn_fails_source_unavailable_nothing_emitted():
    config = cfg(mode="live", dsn="postgresql://postgres@127.0.0.1:9/postgres")
    outcome = run_job(connector, Job.local(config))
    assert outcome.status == "failed"
    assert outcome.error.code == "source_unavailable"
    assert outcome.error.retryable is True
    assert outcome.snapshot is None


def test_live_unset_dsn_env_fails_config_error(monkeypatch):
    monkeypatch.delenv("CTXLAYER_TEST_PG_DSN", raising=False)
    outcome = run_job(connector, Job.local(cfg(mode="live", dsn_env="CTXLAYER_TEST_PG_DSN")))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.snapshot is None


def test_ddl_missing_file_fails_config_error(tmp_path):
    config = cfg(
        mode="ddl-file",
        ddl_files=[str(tmp_path / "absent.sql")],
        image="postgres:16",
    )
    outcome = run_job(connector, Job.local(config))
    assert outcome.status == "failed"
    assert outcome.error.code == "config_error"
    assert outcome.snapshot is None
