"""Validator CLI tests: schema acceptance/rejection and exit codes."""

import copy
import json

import pytest

from snapshot.validate import main, validate_snapshot
from tests.conftest import find_object, load_fixture


def _write(tmp_path, name, snapshot):
    path = tmp_path / name
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    return str(path)


def test_cli_valid_files_exit_zero(tmp_path, supabase, capsys):
    path = _write(tmp_path, "ok.json", supabase)
    assert main([path]) == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize("break_it, fragment", [
    (lambda s: s.pop("connector"), "connector"),
    (lambda s: s.update(snapshot_version="2"), "snapshot_version"),
    (lambda s: s.update(system_class="nosql"), "system_class"),
    (lambda s: s.update(captured_at="yesterday"), "captured_at"),
    (lambda s: s.update(extra_field=1), "extra_field"),
    (lambda s: find_object(s, "orders").update(schema_hash="md5:abc"), "schema_hash"),
    (lambda s: find_object(s, "orders")["columns"][0].pop("ordinal"), "ordinal"),
    (lambda s: find_object(s, "orders")["keys"]["foreign"][0].update(ref="orders"),
     "keys"),
])
def test_cli_schema_violations_exit_nonzero(tmp_path, supabase, capsys,
                                            break_it, fragment):
    bad = copy.deepcopy(supabase)
    break_it(bad)
    path = _write(tmp_path, "bad.json", bad)
    assert main([path]) == 1
    assert "INVALID" in capsys.readouterr().err


def test_cli_unparseable_file_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert main([str(path)]) == 1
    assert "INVALID" in capsys.readouterr().err


def test_duplicate_identity_rejected(supabase):
    bad = copy.deepcopy(supabase)
    bad["objects"].append(copy.deepcopy(find_object(bad, "orders")))
    errors, _ = validate_snapshot(bad)
    assert any("duplicate object identity" in e for e in errors)


def test_check_hashes_flag_catches_mismatch(tmp_path, supabase, capsys):
    bad = copy.deepcopy(supabase)
    find_object(bad, "orders")["schema_hash"] = "sha256:" + "f" * 64
    path = _write(tmp_path, "badhash.json", bad)
    assert main([path]) == 0, "schema-only validation still passes"
    assert main(["--check-hashes", path]) == 1
    assert "C-4" in capsys.readouterr().err


def test_unknown_kind_passes_with_warning(tmp_path, supabase, capsys):
    """S-5: the validator is a consumer — unknown kinds warn, never fail."""
    extended = copy.deepcopy(supabase)
    extended["objects"].append({
        "kind": "function", "schema": "public", "name": "fn_refresh_ltv",
        "description": None, "schema_hash": "sha256:" + "0" * 64,
        "columns": [], "keys": {}, "stats": {},
    })
    path = _write(tmp_path, "extended.json", extended)
    assert main(["--check-hashes", path]) == 0
    captured = capsys.readouterr()
    assert "unknown kind" in captured.err
    assert "OK" in captured.out


def test_drift_pair_and_all_fixtures_via_cli(capsys):
    from tests.conftest import FIXTURES_DIR, FIXTURE_FILES

    paths = [str(FIXTURES_DIR / f) for f in FIXTURE_FILES]
    assert main(["--check-hashes", *paths]) == 0


def test_validate_snapshot_reports_error_paths(supabase):
    bad = copy.deepcopy(supabase)
    find_object(bad, "orders")["columns"][1]["nullable"] = "no"
    errors, _ = validate_snapshot(bad)
    assert len(errors) == 1
    assert "nullable" in errors[0]
