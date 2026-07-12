"""GA4 connector config gate and credential indirection (no network).

Deliverable 1: property ID + service-account credentials via
env-var / file-path indirection — credential *references* only, never
key material in config files, and never key material echoed in errors
(JC-8).
"""

import json

import pytest

from connectors.ga4.connector import _credentials, connector
from connectors.sdk import ConfigError
from connectors.sdk.emission import config_problems


def cfg(**kw) -> dict:
    return {"system": "ga4", "mode": "api", **kw}


CREDS = cfg(property_id="313459823", credentials_env="GA4_SA_JSON")


def test_manifest_declares_api_mode_and_quota_policy():
    assert connector.manifest.metadata_modes() == ("api",)
    assert connector.manifest.rate_limit["strategy"] == "token-bucket"


def test_property_id_required_and_numeric():
    assert any(
        "property_id" in p
        for p in config_problems(connector.manifest, cfg(credentials_env="X"))
    )
    problems = config_problems(
        connector.manifest, cfg(property_id="properties/313459823", credentials_env="X")
    )
    assert problems != []  # resource-name form rejected; config takes the numeric id


def test_credential_reference_required():
    assert config_problems(connector.manifest, cfg(property_id="313459823")) != []
    assert config_problems(connector.manifest, CREDS) == []
    assert (
        config_problems(
            connector.manifest, cfg(property_id="313459823", credentials_file="key.json")
        )
        == []
    )


def test_inline_secrets_have_no_config_slot():
    # There is deliberately no key/private_key/credentials field: schema
    # rejects anything that would put key material into a config file.
    problems = config_problems(
        connector.manifest, {**CREDS, "credentials": {"private_key": "test"}}
    )
    assert problems != []


def test_undeclared_mode_rejected():
    assert config_problems(connector.manifest, cfg(mode="live", property_id="1")) != []


def test_credentials_env_unset_is_config_error(monkeypatch):
    monkeypatch.delenv("GA4_SA_JSON", raising=False)
    with pytest.raises(ConfigError, match="GA4_SA_JSON"):
        _credentials(CREDS)


def test_credentials_env_garbage_not_echoed(monkeypatch):
    secret = '{"private_key": "test"}'
    monkeypatch.setenv("GA4_SA_JSON", secret)
    with pytest.raises(ConfigError) as excinfo:
        _credentials(CREDS)
    assert "hunter2" not in str(excinfo.value)
    assert "not echoed" in str(excinfo.value)


def test_credentials_file_missing_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        _credentials(cfg(property_id="1", credentials_file=str(tmp_path / "absent.json")))


def test_credentials_file_garbage_not_echoed(tmp_path):
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"private_key": "test"}))
    with pytest.raises(ConfigError) as excinfo:
        _credentials(cfg(property_id="1", credentials_file=str(path)))
    assert "hunter2" not in str(excinfo.value)
