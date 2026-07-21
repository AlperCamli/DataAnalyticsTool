"""Backend B parsing/assembly + golden cache (benchmark.backends) — no live."""

import json

import pytest

from benchmark.backends import (
    GoldenCache,
    _assemble_record,
    _backend_b_system,
    _parse_stream,
    load_secrets,
)
from benchmark.executors import ExecResult, ScriptedExecutor
from benchmark.runner import load_prompt
from benchmark.suite import load_suite
from benchmark.validate import DEFAULT_SUITE


@pytest.fixture(scope="module")
def suite():
    return load_suite(DEFAULT_SUITE)


def test_parse_stream_extracts_result_and_reads():
    stream = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/kb/users.md"}}]}}),
        json.dumps({"type": "result", "total_cost_usd": 0.25, "num_turns": 4,
                    "session_id": "sess123", "result": "done",
                    "usage": {"input_tokens": 5, "output_tokens": 100,
                              "cache_read_input_tokens": 90, "cache_creation_input_tokens": 10}}),
    ])
    meta = _parse_stream(stream)
    assert meta["total_cost_usd"] == 0.25
    assert meta["_reads"] == ["read:/kb/users.md"]


def test_assemble_record_merges_log_and_stream(suite, tmp_path):
    case = suite.case("RB-01")
    log = tmp_path / "journey.jsonl"
    log.write_text("\n".join([
        json.dumps({"kind": "discover", "system": "supabase"}),
        json.dumps({"kind": "exec", "seq": 1, "system": "supabase",
                    "request": {"dialect": "sql", "statement": "SELECT count(*) FROM public.users"},
                    "ok": True, "columns": ["n"], "rows": [[42]], "row_count": 1}),
        json.dumps({"kind": "finish", "objects": ["supabase.public.users"], "answer": "42 users"}),
    ]) + "\n", encoding="utf-8")
    stdout = json.dumps({"type": "result", "total_cost_usd": 0.3, "num_turns": 5,
                         "session_id": "s", "result": "42 users",
                         "usage": {"input_tokens": 1, "output_tokens": 50,
                                   "cache_read_input_tokens": 80, "cache_creation_input_tokens": 5}})

    class C:  # minimal condition
        name = "no-kb"; context_root = None; ref = "live-discovery"
    rec = _assemble_record(case, C(), 0, "claude-opus-4-8", "claude-code", "t0", log, stdout)
    assert rec.backend == "claude-code" and rec.cost_usd == 0.3 and rec.model_id == "claude-opus-4-8"
    assert rec.declared_objects == ["supabase.public.users"]
    assert "discover:supabase" in rec.context_reads
    assert len(rec.drafts) == 1 and rec.drafts[0].final and rec.drafts[0].outcome.ok
    assert rec.tokens["output_tokens"] == 50


def test_golden_cache_executes_once_and_counts_ga4(suite):
    responses = {
        "supabase": ExecResult(ok=True, columns=["status", "n"], rows=[["active", 10]], row_count=1),
        "ga4": ExecResult(ok=True, columns=["keyEvents:purchase"], rows=[[120]], row_count=1),
    }
    cache = GoldenCache(ScriptedExecutor(responses))
    case = suite.case("RB-08")  # ga4 + supabase
    a = cache.results_for(case)
    b = cache.results_for(case)  # second call must not re-execute
    assert set(a) == {"ga4", "supabase"}
    assert len(cache.executions) == 2  # once per leg, not per call
    assert cache.ga4_count == 1
    assert a["supabase"].columns == b["supabase"].columns


def test_backend_b_system_prompt_tools_by_condition(suite):
    prompt = load_prompt()

    class Cond:
        def __init__(self, name): self.name = name; self.context_root = None; self.ref = ""
    case = suite.case("RB-08")  # ga4 + supabase
    nokb = _backend_b_system(case, Cond("no-kb"), "cvbuilder", prompt)
    assert "discover_schema" in nokb and "list_context" not in nokb
    assert "run_ga4_report" in nokb and "run_sql" in nokb
    mkb = _backend_b_system(case, Cond("machine-kb"), "cvbuilder", prompt)
    assert "list_context" in mkb and "Read(file_path)" in mkb


def test_load_secrets_parses_dsn(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "env.sh").write_text('export SUPABASE_DSN="postgres://u:p@h/db"\nexport OTHER=1\n')
    (secrets_dir / "ga4-live.json").write_text("{}")
    s = load_secrets(secrets_dir, tmp_path / "snaps")
    assert s.supabase_dsn == "postgres://u:p@h/db"
    assert s.ga4_config and s.ga4_config.endswith("ga4-live.json")
    assert s.gsc_config is None  # not present
