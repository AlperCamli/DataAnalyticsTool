"""Credential-reference resolution (connectors/sdk/vault.py, J-4).

Resolution failure must be the §7 vault-stage auth_error, and no error
message may carry resolved values — only references.
"""

import pytest

from connectors.sdk.vault import (
    EnvResolver,
    VaultResolutionError,
    load_env_file,
)


def test_process_env_resolution(monkeypatch):
    monkeypatch.setenv("CL_TEST_SECRET", "s3cret-value")
    assert EnvResolver.from_process_env().resolve("env://CL_TEST_SECRET") == "s3cret-value"


def test_env_file_resolution(tmp_path):
    env_file = tmp_path / "cl.env"
    env_file.write_text(
        "# local dev vault\n"
        "\n"
        "PLAIN=value1\n"
        "export EXPORTED=value2\n"
        'DOUBLE="quoted value"\n'
        "SINGLE='single quoted'\n"
        "TRAILING=  spaced  \n",
        encoding="utf-8",
    )
    resolver = EnvResolver.from_env_file(env_file)
    assert resolver.resolve("env://PLAIN") == "value1"
    assert resolver.resolve("env://EXPORTED") == "value2"
    assert resolver.resolve("env://DOUBLE") == "quoted value"
    assert resolver.resolve("env://SINGLE") == "single quoted"
    assert resolver.resolve("env://TRAILING") == "spaced"


def test_missing_name_is_vault_stage_auth_error(tmp_path):
    env_file = tmp_path / "cl.env"
    env_file.write_text("OTHER=x\n", encoding="utf-8")
    resolver = EnvResolver.from_env_file(env_file)
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("env://MISSING")
    assert excinfo.value.code == "auth_error"
    assert excinfo.value.retryable is False
    assert excinfo.value.detail == {"stage": "vault"}


def test_unsupported_scheme_rejected():
    with pytest.raises(VaultResolutionError):
        EnvResolver.from_process_env().resolve("vault://kv/data/dsn")


def test_malformed_env_file_rejected(tmp_path):
    env_file = tmp_path / "cl.env"
    env_file.write_text("NOT A LINE\n", encoding="utf-8")
    with pytest.raises(VaultResolutionError):
        load_env_file(env_file)


def test_empty_value_treated_as_unset(monkeypatch):
    monkeypatch.setenv("CL_EMPTY", "")
    with pytest.raises(VaultResolutionError):
        EnvResolver.from_process_env().resolve("env://CL_EMPTY")


def test_error_messages_never_carry_values(tmp_path):
    """JC-8 discipline: references in errors, never resolved material."""
    env_file = tmp_path / "cl.env"
    env_file.write_text("PRESENT=super-secret-canary\n", encoding="utf-8")
    resolver = EnvResolver.from_env_file(env_file)
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("env://ABSENT")
    assert "super-secret-canary" not in str(excinfo.value)
