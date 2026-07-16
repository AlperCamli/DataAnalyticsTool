"""Deliverable 3 — the journey runner + journey prompt v1 (R2, R3).

Drives one journey (case × condition × rep) through a minimal Anthropic
tool loop. The tool surface is guardrailed local executors only (R3); the
model, executor, and snapshot inventory are all injected, so tests run the
whole loop against a scripted client and executor and spend nothing.

Fairness (R2): one journey prompt, identical across conditions except the
context-access section, which is the *only* thing that varies. The prompt
is a versioned repo artifact (``journey-prompt-v1.md``); its version is
recorded on every journey. Execution tools are identical across conditions.

Each journey emits one ``JourneyRecord`` (R3 / skill-spec §8 shape): the
context reads, the agent's self-declared object set, every drafted request
with its execution outcome, token / tool-call counts, model id, and
timestamps. The scorer consumes it; nothing here scores itself.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from benchmark.conditions import ENRICHED_KB, MACHINE_KB, NO_KB, Condition
from benchmark.executors import ExecResult, Executor, ExecutionError
from benchmark.fqn import API_KINDS, SnapshotInventory, object_fqn
from benchmark.journey import Draft, ExecutionOutcome, JourneyRecord
from benchmark.suite import Case

_PKG = Path(__file__).resolve().parent
JOURNEY_PROMPT_PATH = _PKG / "prompts" / "journey-prompt-v1.md"
JOURNEY_PROMPT_VERSION = "v1"
DEFAULT_MODEL_ID = "claude-opus-4-8"
MAX_ITERATIONS = 12

# systems whose leg is SQL (dialect chosen from the case's golden legs).
_SQL_SYSTEMS = frozenset({"supabase"})


# --------------------------------------------------------------------------
# model client abstraction (injected; the live wrapper is optional)


@dataclass
class ModelResponse:
    content: list[Any]
    stop_reason: str
    usage: Mapping[str, int]


class ModelClient(Protocol):
    def create(self, *, system: str, messages: list, tools: list) -> ModelResponse: ...


class AnthropicModelClient:
    """Live client — a thin wrapper over ``client.messages.create`` (pinned model)."""

    def __init__(self, client, *, model: str = DEFAULT_MODEL_ID,
                 max_tokens: int = 16000, effort: str = "high"):
        self._client = client
        self.model = model
        self._max_tokens = max_tokens
        self._effort = effort

    def create(self, *, system, messages, tools) -> ModelResponse:
        resp = self._client.messages.create(
            model=self.model, max_tokens=self._max_tokens, system=system,
            tools=tools, messages=messages,
            thinking={"type": "adaptive"}, output_config={"effort": self._effort},
        )
        u = resp.usage
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        }
        return ModelResponse(content=list(resp.content), stop_reason=resp.stop_reason, usage=usage)


# --------------------------------------------------------------------------
# prompt (versioned artifact; only the context-access section varies)


def load_prompt(path: Path = JOURNEY_PROMPT_PATH) -> tuple[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8")
    marker = re.compile(r"<!-- CONTEXT-ACCESS: (\S+) -->")
    parts = marker.split(text)
    body = parts[0].rstrip() + "\n"
    variants: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        name = parts[i]
        chunk = parts[i + 1].split("<!-- END -->")[0].strip()
        variants[name] = chunk
    return body, variants


def render_prompt(condition: str, customer: str, systems: Sequence[str],
                  body: str, variants: Mapping[str, str]) -> str:
    return (
        body.replace("{customer}", customer)
        .replace("{systems}", ", ".join(systems))
        .replace("{{CONTEXT_ACCESS}}", variants[condition])
    )


# --------------------------------------------------------------------------
# context providers (the condition-specific affordance)


def snapshot_discovery(snapshots: Sequence[Mapping[str, Any]], system: str) -> str:
    """Live-discovery payload for no-kb: the system's introspected structure.

    The snapshot *is* the introspection output, so serving it is faithful to
    'introspect information_schema / the metadata endpoint' — and keeps the
    run deterministic and free of extra live calls.
    """
    snap = next((s for s in snapshots if s["system"] == system), None)
    if snap is None:
        return json.dumps({"error": f"unknown system {system}"})
    out: dict[str, Any] = {"system": system, "system_class": snap.get("system_class")}
    # Introspection knows which property/site it is querying (the service
    # account lists it); without this, no-kb agents cannot ground the
    # `property` argument of the GA4/GSC executors at all.
    if snap.get("source_properties"):
        out["source_properties"] = snap["source_properties"]
    if snap.get("system_class") == "sql":
        out["tables"] = [
            {"schema": o["schema"], "name": o["name"], "kind": o["kind"],
             "columns": [{"name": c["name"], "type": c["type"], "nullable": c["nullable"]}
                         for c in sorted(o.get("columns", []), key=lambda c: c["ordinal"])]}
            for o in sorted(snap["objects"], key=lambda o: (o["schema"], o["name"]))
        ]
    else:
        out["objects"] = [
            {"schema": o["schema"], "name": o["name"], "kind": o["kind"],
             "data_type": o.get("stats", {}).get("data_type")}
            for o in sorted(snap["objects"], key=lambda o: (o["kind"], o["name"]))
        ]
    return json.dumps(out, ensure_ascii=False)


def _list_context(root: Path) -> str:
    files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                   if p.is_file() and not p.name.startswith(".") and ".git/" not in p.as_posix())
    return json.dumps({"documents": files})


def _read_context(root: Path, rel: str) -> str:
    target = (root / rel).resolve()
    if not str(target).startswith(str(root.resolve())) or not target.is_file():
        return json.dumps({"error": f"not found: {rel}"})
    return target.read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------
# tool definitions (per case; identical across conditions except context tools)


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required, "additionalProperties": False}}


def build_tools(case: Case, condition: str) -> list[dict]:
    tools: list[dict] = []
    if condition == NO_KB:
        tools.append(_tool("discover_schema", "Introspect a system's live structure.",
                           {"system": {"type": "string", "enum": list(case.systems)}}, ["system"]))
    else:
        tools.append(_tool("list_context", "List available knowledge-base documents.", {}, []))
        tools.append(_tool("read_context", "Read one knowledge-base document by path.",
                           {"path": {"type": "string"}}, ["path"]))
    if any(s in _SQL_SYSTEMS for s in case.systems):
        tools.append(_tool("run_sql", "Run one SELECT-only Postgres query (30s timeout, 10k rows).",
                           {"statement": {"type": "string"}}, ["statement"]))
    if "ga4" in case.systems:
        tools.append(_tool("run_ga4_report", "Run one GA4 runReport.",
                           {"property": {"type": "string"}, "body": {"type": "object"}},
                           ["property", "body"]))
    if "gsc" in case.systems:
        tools.append(_tool("run_gsc_query", "Run one Search Console searchanalytics query.",
                           {"property": {"type": "string"}, "body": {"type": "object"}},
                           ["property", "body"]))
    tools.append(_tool("finish", "Finalize: declare the objects your final query used and the answer.",
                       {"objects": {"type": "array", "items": {"type": "string"}},
                        "answer": {"type": "string"}}, ["objects", "answer"]))
    return tools


# --------------------------------------------------------------------------
# the journey loop


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _sql_system(case: Case) -> str:
    return next((s for s in case.systems if s in _SQL_SYSTEMS), "supabase")


def _blocks(content: list[Any], kind: str) -> list[Any]:
    return [b for b in content if getattr(b, "type", None) == kind]


def run_journey(
    case: Case,
    condition: Condition,
    rep: int,
    *,
    model_client: ModelClient,
    executor: Executor,
    snapshots: Sequence[Mapping[str, Any]],
    prompt: tuple[str, Mapping[str, str]] | None = None,
    model_id: str = DEFAULT_MODEL_ID,
    customer: str = "the customer",
    max_iterations: int = MAX_ITERATIONS,
) -> JourneyRecord:
    body, variants = prompt or load_prompt()
    system_prompt = render_prompt(condition.name, customer, case.systems, body, variants)
    tools = build_tools(case, condition.name)
    sql_system = _sql_system(case)

    record = JourneyRecord(
        case_id=case.id, condition=condition.name, rep=rep, model_id=model_id,
        started_at=_now(),
    )
    tokens = {"input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    messages: list[dict] = [{"role": "user", "content": case.request}]
    seq = 0
    finished = False

    def handle_tool(block) -> tuple[str, bool]:
        """Execute one tool call -> (result content, is_error). Records drafts/reads."""
        nonlocal seq
        name = block.name
        args = block.input or {}
        if name == "discover_schema":
            record.context_reads.append(f"discover:{args.get('system')}")
            return snapshot_discovery(snapshots, args.get("system", "")), False
        if name == "list_context":
            record.context_reads.append("list_context")
            return _list_context(condition.context_root), False
        if name == "read_context":
            record.context_reads.append(f"read:{args.get('path')}")
            return _read_context(condition.context_root, args.get("path", "")), False
        if name in ("run_sql", "run_ga4_report", "run_gsc_query"):
            seq += 1
            try:
                if name == "run_sql":
                    request = {"dialect": "sql", "statement": args.get("statement", "")}
                    system = sql_system
                    res = executor.run_sql(sql_system, args.get("statement", ""))
                elif name == "run_ga4_report":
                    request = {"dialect": "api", "operation": "runReport",
                               "property": args.get("property", ""), "body": args.get("body", {})}
                    system = "ga4"
                    res = executor.run_api("ga4", "runReport", args.get("property", ""), args.get("body", {}))
                else:
                    request = {"dialect": "api", "operation": "searchanalytics.query",
                               "property": args.get("property", ""), "body": args.get("body", {})}
                    system = "gsc"
                    res = executor.run_api("gsc", "searchanalytics.query", args.get("property", ""),
                                           args.get("body", {}))
            except ExecutionError as exc:
                # a guard rejection is an unexecutable draft, not a crash
                res = ExecResult(ok=False, error=str(exc))
            outcome = ExecutionOutcome(
                ok=res.ok, error=res.error, row_count=res.row_count,
                columns=res.columns, rows=res.rows, elapsed_ms=res.elapsed_ms,
            )
            record.drafts.append(Draft(seq=seq, system=system, request=request,
                                       complete=True, executed=True, outcome=outcome))
            if res.ok:
                preview = {"columns": res.columns, "row_count": res.row_count,
                           "rows": res.rows[:50], "truncated": res.truncated}
                return json.dumps(preview, default=str), False
            return json.dumps({"error": res.error}), True
        return json.dumps({"error": f"unknown tool {name}"}), True

    for _ in range(max_iterations):
        record.tool_calls += 1
        resp = model_client.create(system=system_prompt, messages=messages, tools=tools)
        for k in tokens:
            tokens[k] += resp.usage.get(k, 0)
        tool_uses = _blocks(resp.content, "tool_use")
        if not tool_uses:
            break
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in tool_uses:
            if block.name == "finish":
                record.declared_objects = list((block.input or {}).get("objects", []))
                record.notes = (block.input or {}).get("answer", "")
                finished = True
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": "recorded"})
                continue
            content, is_error = handle_tool(block)
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})
        if finished:
            break

    _mark_final(record)
    record.tokens = tokens
    record.ended_at = _now()
    return record


def _mark_final(record: JourneyRecord) -> None:
    """The agent's answer per system = its last successful execution there."""
    last_ok: dict[str, int] = {}
    for d in record.drafts:
        if d.executed and d.outcome and d.outcome.ok:
            last_ok[d.system] = d.seq
    for d in record.drafts:
        d.final = last_ok.get(d.system) == d.seq
