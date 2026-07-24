"""Manual-baseline kit (benchmark.manual) — no live access, no model calls."""

import json
import subprocess
from pathlib import Path

import pytest

from benchmark import manual
from benchmark.manual import (
    BACKEND_ID,
    CONDITIONS,
    MANUAL_PROMPT_PATH,
    _validate_log,
    main,
    record_from_log,
    render_manual_prompt,
)
from benchmark.runner import load_prompt
from benchmark.suite import load_suite
from benchmark.validate import DEFAULT_SUITE


@pytest.fixture(scope="module")
def suite():
    return load_suite(DEFAULT_SUITE)


@pytest.fixture()
def isolated_home(tmp_path, monkeypatch):
    """Point Path.home() away from the real home so preflight sees no
    ~/.claude/CLAUDE.md regardless of the dev machine's state."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture()
def kb_repo(tmp_path):
    """A tiny customer-KB git repo to export as the enriched condition."""
    src = tmp_path / "kb-src"
    src.mkdir()
    (src / "index.md").write_text("# kb\n", encoding="utf-8")
    (src / "systems").mkdir()
    (src / "systems" / "supabase.md").write_text("enriched notes\n", encoding="utf-8")
    env_git = ["git", "-C", str(src), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "-C", str(src), "init", "-q"], check=True)
    subprocess.run(env_git + ["add", "-A"], check=True)
    subprocess.run(env_git + ["commit", "-qm", "kb"], check=True)
    return src


def _build(tmp_path, kb_repo, *extra):
    root = tmp_path / "runs"
    rc = main(["conditions", "--root", str(root), "--kb", str(kb_repo), *extra])
    return root, rc


# --------------------------------------------------------------------------
# prompt variant (deliverable 5)


def test_manual_prompt_parses_with_three_variants():
    body, variants = load_prompt(MANUAL_PROMPT_PATH)
    assert set(variants) == set(CONDITIONS)
    # transport naming: MCP-prefixed executor tools, actual signatures.
    assert "mcp__executor__run_sql(statement)" in body
    assert "mcp__executor__finish" in body
    assert "run_sql(system, statement)" not in body  # v1's wrong signature fixed
    assert "read_context" not in body + "".join(variants.values())  # tool doesn't exist


def test_manual_prompt_variants_scope_their_own_affordance():
    _, variants = load_prompt(MANUAL_PROMPT_PATH)
    assert "mcp__executor__discover_schema" in variants["no-kb"]
    assert "list_context" not in variants["no-kb"]
    for cond in ("machine-kb", "enriched-kb"):
        assert "mcp__executor__list_context" in variants[cond]
        assert "`Read`" in variants[cond]
        assert "discover_schema" not in variants[cond]


def test_rendered_prompt_is_paste_ready_and_leak_free(suite):
    out = render_manual_prompt(suite, "RB-01", "no-kb")
    case = suite.case("RB-01")
    assert case.request.strip() in out
    assert "cvbuilder" in out
    assert "MANUAL-TRANSPORT" not in out  # provenance comment never renders
    assert "{customer}" not in out and "{{CONTEXT_ACCESS}}" not in out


def test_rendered_prompts_differ_only_in_context_access(suite):
    body, variants = load_prompt(MANUAL_PROMPT_PATH)
    outs = {c: render_manual_prompt(suite, "RB-05", c) for c in CONDITIONS}
    for cond, text in outs.items():
        rest = text.replace(variants[cond], "{{CONTEXT_ACCESS}}")
        base = outs[CONDITIONS[0]].replace(variants[CONDITIONS[0]], "{{CONTEXT_ACCESS}}")
        assert rest == base  # R2: identical outside the context-access section


def test_prompt_unknown_case_fails_cleanly(suite):
    with pytest.raises(SystemExit):
        render_manual_prompt(suite, "RB-99", "no-kb")


def test_no_kb_discovery_grounds_the_property_ids():
    """A no-kb agent must be able to ground run_ga4_report/run_gsc_query's
    `property` argument from discovery alone (the requests never name it)."""
    from benchmark.runner import snapshot_discovery
    from benchmark.validate import DEFAULT_SNAPSHOTS, load_snapshots

    snaps = load_snapshots(DEFAULT_SNAPSHOTS)
    ga4 = json.loads(snapshot_discovery(snaps, "ga4"))
    assert ga4["source_properties"]["property_id"].startswith("properties/")
    gsc = json.loads(snapshot_discovery(snaps, "gsc"))
    assert any(p.get("site_url", "").startswith("sc-domain:")
               for p in gsc["source_properties"]["properties"])


# --------------------------------------------------------------------------
# conditions (deliverable 1)


def test_conditions_build_invariants(tmp_path, isolated_home, kb_repo):
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 0

    mcps = [(root / c / ".mcp.json").read_bytes() for c in CONDITIONS]
    assert mcps[0] == mcps[1] == mcps[2]  # byte-identical across conditions
    text = mcps[0].decode()
    assert "${BENCHMARK_JOURNEY_LOG}" in text and "${SUPABASE_DSN}" in text
    assert "${PWD}/kb" in text
    assert "postgres://" not in text  # no secret material on disk

    assert sorted(p.name for p in (root / "no-kb").iterdir()) == [".mcp.json", "records"]
    assert (root / "machine-kb" / "kb" / "index.md").is_file()
    assert (root / "enriched-kb" / "kb" / "systems" / "supabase.md").is_file()
    assert not (root / "enriched-kb" / "kb" / ".git").exists()

    manifest = json.loads((root / "manifest.json").read_text())
    assert manifest["backend"] == BACKEND_ID
    assert set(manifest["kb_refs"]) == set(CONDITIONS)
    assert manifest["kb_refs"]["machine-kb"].startswith("sha256:")
    assert len(manifest["kb_refs"]["enriched-kb"]) == 40  # pinned git sha
    assert manifest["snapshot_refs"]  # per-system snapshot hashes recorded
    assert manifest["journey_prompt"]["version"] == "v1"


def test_conditions_refuses_existing_without_force(tmp_path, isolated_home, kb_repo):
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 0
    marker = root / "no-kb" / "records" / "RB-01.no-kb.0.jsonl"
    marker.write_text("{}\n", encoding="utf-8")
    _, rc = _build(tmp_path, kb_repo)
    assert rc == 2  # refuses to rebuild
    root2, rc = _build(tmp_path, kb_repo, "--force")
    assert rc == 0 and marker.is_file()  # rebuild preserves records/


def test_conditions_preflight_refuses_claude_md_ancestor(tmp_path, isolated_home, kb_repo):
    (tmp_path / "CLAUDE.md").write_text("project memory\n", encoding="utf-8")
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 2 and not (root / "no-kb").exists()


# --------------------------------------------------------------------------
# ingest (deliverable 2 — R3 records from executor logs)


def _journey_log_lines(statement="SELECT count(*) FROM public.users"):
    return [
        json.dumps({"kind": "discover", "system": "supabase"}),
        json.dumps({"kind": "exec", "seq": 1, "system": "supabase",
                    "request": {"dialect": "sql", "statement": statement},
                    "ok": True, "columns": ["n"], "rows": [[7]], "row_count": 1,
                    "truncated": False, "elapsed_ms": 12.5}),
        json.dumps({"kind": "finish", "objects": ["supabase.public.WRONG_SELF_REPORT"],
                    "answer": "7"}),
    ]


def test_record_from_log_nulls_unmeasurable_fields(tmp_path):
    log = tmp_path / "RB-01.no-kb.0.jsonl"
    log.write_text("\n".join(_journey_log_lines()) + "\n", encoding="utf-8")
    rec = record_from_log(log, "RB-01", "no-kb", 0, "claude-opus-4-8")
    assert rec.backend == BACKEND_ID and rec.cost_usd is None and rec.session_id == ""
    assert all(v is None for v in rec.tokens.values())
    assert rec.tool_calls == 3  # executor calls, not turns
    assert rec.started_at and rec.ended_at
    assert len(rec.drafts) == 1 and rec.drafts[0].final and rec.drafts[0].outcome.ok
    assert rec.context_reads == ["discover:supabase"]
    assert rec.declared_objects == ["supabase.public.WRONG_SELF_REPORT"]


def test_validate_log_flags_double_finish_and_no_exec(tmp_path):
    log = tmp_path / "x.jsonl"
    log.write_text(json.dumps({"kind": "finish", "objects": [], "answer": ""}) + "\n" * 2
                   + json.dumps({"kind": "finish", "objects": [], "answer": ""}) + "\n",
                   encoding="utf-8")
    problems = _validate_log(log)
    assert any("finish" in p for p in problems)
    assert any("no executed request" in p for p in problems)


# --------------------------------------------------------------------------
# ingest + score end-to-end (offline: --no-golden)


def test_ingest_then_score_offline(tmp_path, isolated_home, kb_repo, capsys):
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 0
    log = root / "no-kb" / "records" / "RB-01.no-kb.0.jsonl"
    log.write_text("\n".join(_journey_log_lines()) + "\n", encoding="utf-8")

    assert main(["ingest", "--root", str(root)]) == 0
    record_path = root / "no-kb" / "records" / "RB-01.no-kb.0.json"
    data = json.loads(record_path.read_text())
    assert data["case_id"] == "RB-01" and data["backend"] == BACKEND_ID

    out = tmp_path / "results"
    assert main(["score", "--root", str(root), "--out", str(out), "--no-golden"]) == 0
    run_dir = next(out.iterdir())
    artifact = json.loads((run_dir / "results.json").read_text())
    assert artifact["run"]["backend"] == BACKEND_ID
    assert artifact["run"]["kind"] == "manual-baseline"
    assert artifact["run"]["kb_refs"]["machine-kb"].startswith("sha256:")
    (j,) = artifact["journeys"]
    # R4: selection is parser-extracted from the executed statement — the
    # bogus self-declared list must not leak into the scored set.
    assert j["selection"]["scored"] == ["supabase.public.users"]
    assert j["selection"]["recall"] == 1.0
    assert j["selection"]["declared"] == ["supabase.public.WRONG_SELF_REPORT"]
    assert j["correctness"]["scored"] is False  # --no-golden -> unscored
    assert (run_dir / "report.md").is_file()


def test_score_rejects_filename_content_mismatch(tmp_path, isolated_home, kb_repo):
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 0
    log = root / "no-kb" / "records" / "RB-01.no-kb.0.jsonl"
    log.write_text("\n".join(_journey_log_lines()) + "\n", encoding="utf-8")
    assert main(["ingest", "--root", str(root)]) == 0
    good = root / "no-kb" / "records" / "RB-01.no-kb.0.json"
    good.rename(root / "no-kb" / "records" / "RB-02.no-kb.1.json")
    assert main(["score", "--root", str(root), "--out", str(tmp_path / "r"),
                 "--no-golden"]) == 1


def test_finder_ds_store_is_not_drift(tmp_path, isolated_home, kb_repo):
    """macOS drops .DS_Store into browsed dirs; it must trip neither the
    drift guard nor the stray-file invariant."""
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 0
    (root / "machine-kb" / "kb" / ".DS_Store").write_bytes(b"\x00finder")
    (root / "no-kb" / ".DS_Store").write_bytes(b"\x00finder")
    log = root / "no-kb" / "records" / "RB-01.no-kb.0.jsonl"
    log.write_text("\n".join(_journey_log_lines()) + "\n", encoding="utf-8")
    assert main(["ingest", "--root", str(root)]) == 0
    assert main(["preflight", "--root", str(root)]) == 0
    assert main(["score", "--root", str(root), "--out", str(tmp_path / "r"),
                 "--no-golden"]) == 0


def test_score_refuses_condition_drift(tmp_path, isolated_home, kb_repo):
    root, rc = _build(tmp_path, kb_repo)
    assert rc == 0
    (root / "machine-kb" / "kb" / "index.md").write_text("tampered\n", encoding="utf-8")
    assert main(["score", "--root", str(root), "--out", str(tmp_path / "r"),
                 "--no-golden"]) == 2
