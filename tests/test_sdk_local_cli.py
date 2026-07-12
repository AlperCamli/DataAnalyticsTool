"""Local CLI transport — the task's exit criteria live here.

Exit criterion 1: the static demo runs through the CLI, validates, and
emits a canonical snapshot file. Exit criterion 2: an injected
mid-introspection error produces a failed job and no output file.
"""

import json

from connectors.sdk.local import EXIT_DEFERRED, EXIT_FAILED, EXIT_OK, EXIT_USAGE, main
from snapshot.canonical import canonical_body_bytes
from snapshot.validate import validate_snapshot

DEMO = "connectors.static_demo.connector:connector"


def write_config(tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def run_cli(tmp_path, config, out_name="snap.json"):
    cfg = write_config(tmp_path, config)
    out = tmp_path / out_name
    rc = main([DEMO, "--config", str(cfg), "--out", str(out)])
    return rc, out


def test_exit_criterion_success(tmp_path, capsys):
    rc, out = run_cli(tmp_path, {"system": "demo", "mode": "ddl-file"})
    assert rc == EXIT_OK
    raw = out.read_bytes()
    assert raw.endswith(b"\n")
    doc = json.loads(raw)
    assert validate_snapshot(doc, check_hashes=True) == ([], [])
    assert doc["system"] == "demo"
    assert len(doc["objects"]) == 2
    assert "OK" in capsys.readouterr().out


def test_exit_criterion_injected_failure_no_output(tmp_path, capsys):
    rc, out = run_cli(
        tmp_path, {"system": "demo", "mode": "ddl-file", "inject_failure": "source_unavailable"}
    )
    assert rc == EXIT_FAILED
    assert not out.exists()  # S-6: failed job leaves nothing behind
    err = capsys.readouterr().err
    assert "FAILED source_unavailable" in err
    assert "retryable" in err


def test_reruns_are_canonical_body_identical(tmp_path):
    rc1, out1 = run_cli(tmp_path, {"system": "demo", "mode": "ddl-file"}, "a.json")
    rc2, out2 = run_cli(tmp_path, {"system": "demo", "mode": "ddl-file"}, "b.json")
    assert rc1 == rc2 == EXIT_OK
    body1 = canonical_body_bytes(json.loads(out1.read_bytes()))
    body2 = canonical_body_bytes(json.loads(out2.read_bytes()))
    assert body1 == body2  # C-2: only captured_at may differ


def test_quota_deferral_distinct_exit_code(tmp_path, capsys):
    rc, out = run_cli(
        tmp_path, {"system": "demo", "mode": "ddl-file", "inject_failure": "quota"}
    )
    assert rc == EXIT_DEFERRED
    assert not out.exists()
    assert "DEFERRED retry_after_s=3600" in capsys.readouterr().err


def test_config_error_no_output(tmp_path, capsys):
    rc, out = run_cli(tmp_path, {"system": "demo", "mode": "live"})
    assert rc == EXIT_FAILED
    assert not out.exists()
    assert "config_error" in capsys.readouterr().err


def test_bad_connector_spec_is_usage_error(tmp_path, capsys):
    cfg = write_config(tmp_path, {"system": "demo", "mode": "ddl-file"})
    rc = main(["connectors.no_such_module:connector",
               "--config", str(cfg), "--out", str(tmp_path / "x.json")])
    assert rc == EXIT_USAGE
    assert "cannot load connector" in capsys.readouterr().err


def test_attr_that_is_not_a_connector_is_usage_error(tmp_path, capsys):
    cfg = write_config(tmp_path, {"system": "demo", "mode": "ddl-file"})
    rc = main(["connectors.sdk.local:main",
               "--config", str(cfg), "--out", str(tmp_path / "x.json")])
    assert rc == EXIT_USAGE
    assert "expected a Connector instance" in capsys.readouterr().err


def test_unreadable_config_is_usage_error(tmp_path, capsys):
    out = tmp_path / "x.json"
    rc = main([DEMO, "--config", str(tmp_path / "missing.json"), "--out", str(out)])
    assert rc == EXIT_USAGE
    assert not out.exists()


def test_default_attr_is_connector(tmp_path):
    cfg = write_config(tmp_path, {"system": "demo", "mode": "ddl-file"})
    out = tmp_path / "snap.json"
    assert main(["connectors.static_demo.connector",
                 "--config", str(cfg), "--out", str(out)]) == EXIT_OK
    assert out.exists()
