"""Journey runner + prompt v1 (benchmark.runner, R2/R3) — scripted, zero spend."""

import json
from types import SimpleNamespace

import pytest

from benchmark.conditions import (
    build_machine_kb,
    enriched_kb_condition,
    no_kb_condition,
)
from benchmark.executors import ExecResult, ScriptedExecutor
from benchmark.fqn import SnapshotInventory
from benchmark.runner import (
    JOURNEY_PROMPT_VERSION,
    ModelResponse,
    build_tools,
    load_prompt,
    render_prompt,
    run_journey,
)
from benchmark.scoring import score_journey
from benchmark.suite import load_suite
from benchmark.validate import DEFAULT_SNAPSHOTS, DEFAULT_SUITE, load_snapshots


def _tu(name, **inp):
    return SimpleNamespace(type="tool_use", id=f"tu_{name}_{id(inp)}", name=name, input=inp)


def _text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClient:
    """Replays scripted turns; reports token usage like the SDK."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0
        self.last_system = None
        self.last_tools = None

    def create(self, *, system, messages, tools):
        self.last_system, self.last_tools = system, tools
        turn = self.turns[self.calls]
        self.calls += 1
        has_tool = any(getattr(b, "type", None) == "tool_use" for b in turn)
        return ModelResponse(
            content=turn,
            stop_reason="tool_use" if has_tool else "end_turn",
            usage={"input_tokens": 100, "output_tokens": 20,
                   "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        )


@pytest.fixture(scope="module")
def snapshots():
    return load_snapshots(DEFAULT_SNAPSHOTS)


@pytest.fixture(scope="module")
def inventory(snapshots):
    return SnapshotInventory(snapshots)


@pytest.fixture(scope="module")
def suite():
    return load_suite(DEFAULT_SUITE)


# -- prompt (R2) -----------------------------------------------------------

def test_prompt_loads_three_variants():
    body, variants = load_prompt()
    assert set(variants) == {"no-kb", "machine-kb", "enriched-kb"}
    assert "{{CONTEXT_ACCESS}}" in body
    assert JOURNEY_PROMPT_VERSION == "v1"


def test_prompt_differs_only_in_context_section():
    body, variants = load_prompt()
    systems = ["supabase"]
    p_nokb = render_prompt("no-kb", "cvbuilder", systems, body, variants)
    p_mkb = render_prompt("machine-kb", "cvbuilder", systems, body, variants)
    # The shared body (everything that isn't the variant) is identical.
    shared = body.replace("{{CONTEXT_ACCESS}}", "").replace("{customer}", "cvbuilder").replace("{systems}", "supabase")
    for line in shared.splitlines():
        if line.strip():
            assert line in p_nokb and line in p_mkb
    assert variants["no-kb"] in p_nokb and variants["no-kb"] not in p_mkb
    assert variants["machine-kb"] in p_mkb


# -- tool surface ----------------------------------------------------------

def test_tool_surface_matches_case_systems(suite):
    names_sql = {t["name"] for t in build_tools(suite.case("RB-01"), "machine-kb")}
    assert {"run_sql", "list_context", "read_context", "finish"} <= names_sql
    assert "run_ga4_report" not in names_sql
    names_multi = {t["name"] for t in build_tools(suite.case("RB-08"), "no-kb")}
    assert {"run_sql", "run_ga4_report", "discover_schema", "finish"} <= names_multi
    assert "read_context" not in names_multi  # no-kb has no KB reads


# -- journeys (kb, no-kb, multi-leg, guard) --------------------------------

def test_kb_journey_reads_context_runs_sql_finishes(tmp_path, snapshots, inventory, suite):
    case = suite.case("RB-01")
    build = build_machine_kb(tmp_path / "mkb")
    cond = SimpleNamespace(name="machine-kb", context_root=build.out_dir, ref=build.ref)
    sql = "SELECT date_trunc('day', created_at)::date d, count(*) n FROM public.users GROUP BY 1"
    client = FakeClient([
        [_tu("read_context", path="systems/supabase/public/users.schema.md")],
        [_text("Drafting."), _tu("run_sql", statement=sql)],
        [_tu("finish", objects=["supabase.public.users"], answer="Daily new users in June.")],
    ])
    ex = ScriptedExecutor({"supabase:sql": ExecResult(ok=True, columns=["d", "n"], rows=[["2026-06-01", 9]], row_count=1)})
    rec = run_journey(case, cond, 0, model_client=client, executor=ex, snapshots=snapshots)

    assert rec.condition == "machine-kb" and rec.model_id == "claude-opus-4-8"
    assert any(r.startswith("read:") for r in rec.context_reads)
    finals = rec.final_drafts()
    assert len(finals) == 1 and finals[0].system == "supabase" and finals[0].outcome.ok
    assert rec.declared_objects == ["supabase.public.users"]
    assert rec.tokens["input_tokens"] == 300 and rec.ended_at
    scored = score_journey(rec, case, inventory)
    assert scored.selection.precision == 1.0 and scored.selection.recall == 1.0
    assert scored.executable.first_try_executable


def test_nokb_journey_discovers_then_executes(tmp_path, snapshots, inventory, suite):
    case = suite.case("RB-09")
    cond = no_kb_condition()
    client = FakeClient([
        [_tu("discover_schema", system="supabase")],
        [_tu("run_sql", statement="SELECT status, count(*) FROM public.ai_runs GROUP BY 1")],
        [_tu("finish", objects=["supabase.public.ai_runs"], answer="Failure rate by day.")],
    ])
    ex = ScriptedExecutor()
    rec = run_journey(case, cond, 1, model_client=client, executor=ex, snapshots=snapshots)
    assert "discover:supabase" in rec.context_reads
    assert rec.final_drafts()[0].system == "supabase"
    scored = score_journey(rec, case, inventory)
    assert scored.selection.recall == 1.0


def test_multi_leg_journey_two_final_drafts(tmp_path, snapshots, inventory, suite):
    case = suite.case("RB-08")
    cond = no_kb_condition()
    client = FakeClient([
        [_tu("run_ga4_report", property="properties/000000000",
             body={"dateRanges": [{"startDate": "2026-06-01", "endDate": "2026-06-30"}],
                   "metrics": [{"name": "keyEvents:purchase"}, {"name": "purchaseRevenue"}]})],
        [_tu("run_sql", statement="SELECT status, count(*) FROM public.subscriptions GROUP BY 1")],
        [_tu("finish", objects=["ga4.standard.keyEvents:purchase", "ga4.standard.purchaseRevenue",
                                "supabase.public.subscriptions"], answer="Reconciliation.")],
    ])
    ex = ScriptedExecutor()
    rec = run_journey(case, cond, 0, model_client=client, executor=ex, snapshots=snapshots)
    systems = {d.system for d in rec.final_drafts()}
    assert systems == {"ga4", "supabase"}
    scored = score_journey(rec, case, inventory)
    assert scored.selection.recall == 1.0 and scored.selection.precision == 1.0


def test_guard_rejection_is_unexecutable_not_crash(tmp_path, snapshots, inventory, suite):
    case = suite.case("RB-01")
    cond = no_kb_condition()
    client = FakeClient([
        [_tu("run_sql", statement="DELETE FROM public.users")],  # guard refuses
        [_tu("finish", objects=[], answer="Could not run.")],
    ])
    ex = ScriptedExecutor()
    rec = run_journey(case, cond, 0, model_client=client, executor=ex, snapshots=snapshots)
    draft = rec.drafts[0]
    assert draft.executed and not draft.outcome.ok and "refused" in draft.outcome.error
    scored = score_journey(rec, case, inventory)
    assert not scored.executable.first_try_executable


def test_iteration_cap_terminates(tmp_path, snapshots, suite):
    case = suite.case("RB-01")
    cond = no_kb_condition()
    # A model that never finishes — the cap must stop it.
    turns = [[_tu("run_sql", statement="SELECT 1")] for _ in range(50)]
    client = FakeClient(turns)
    ex = ScriptedExecutor()
    rec = run_journey(case, cond, 0, model_client=client, executor=ex, snapshots=snapshots, max_iterations=5)
    assert client.calls == 5 and rec.ended_at
