"""Behavioral skill scenarios — the AS-9/10/12 gate evidence (D-78 layer (b)).

These are the conformance evidence, not the rule validators in
`skill_conformance.py`. Per D-78: *a conformance item may only be reported
green on evidence that could have failed if the behavior were absent.*
Each scenario runs a real skill in a real headless Claude Code session
against the fixture deployment (skill-spec §9), then asserts on the audit
stream and the files the agent produced. If the skill misbehaved, these
fail; that is the whole point.

Two journeys cover the three items:

* **enrich `shop.orders`** — AS-12 (purposes in front-matter, no body
  section restating them) and AS-9 (the one deliberately unanswerable
  column, `discount`, lands as a gap, never as a guessed one-liner).
* **report net sales** — AS-10 (the request routes through a `warn-user`
  doc, and the warning travels into the report artifact's `trust_notes`,
  not only the transcript).

Run against a live fixture deployment:

    node_modules/.bin/vite-node test/fixture-deployment.ts -- \
        --out /tmp/fixture.json --with-execution      # in core/, kept up
    .venv/bin/python -m tools.skill_scenarios \
        --connection /tmp/fixture.json \
        --model claude-opus-4-8 \
        --out results/cp5-scenarios

Cost is the operating user's responsibility (D-77); this gates nothing on
it. Records + audit extracts are written under --out as the committed gate
evidence, and the scenarios re-run on any skill edit (D-78.3).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO / "core" / "skills"


@dataclass
class Assertion:
    name: str
    ok: bool
    detail: str


@dataclass
class ScenarioResult:
    scenario: str
    skill: str
    profile: str
    assertions: list[Assertion] = field(default_factory=list)
    agent_result: str = ""
    session_id: str = ""
    cost_usd: float | None = None
    audit_tools: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.assertions) and all(a.ok for a in self.assertions)


# --------------------------------------------------------------------------
# headless Claude Code invocation


def _mcp_config(mcp_url: str, profile: str, token: str) -> dict:
    return {
        "mcpServers": {
            "contextlayer": {
                "type": "http",
                "url": f"{mcp_url}?profile={profile}",
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    }


def _prepare_workdir(workdir: Path, skill: str, mcp_config: dict) -> None:
    """A session working dir: the one skill under test, its MCP config.

    Only the skill being tested is installed — a scenario that passed
    because a *different* skill's instructions leaked in would be measuring
    nothing.
    """
    skill_dst = workdir / ".claude" / "skills" / skill
    skill_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy(SKILLS_DIR / skill / "SKILL.md", skill_dst / "SKILL.md")
    (workdir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n")


def _run_agent(workdir: Path, prompt: str, model: str, allowed_tools: list[str], timeout_s: int) -> dict:
    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--mcp-config", str(workdir / ".mcp.json"),
        "--strict-mcp-config",
        "--add-dir", str(workdir),
        "--allowedTools", ",".join(allowed_tools),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir, timeout=timeout_s)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr.strip()[:400]}")
    return json.loads(proc.stdout)


def _audit_tools(ops_db_url: str, profile: str, since: datetime) -> list[dict]:
    """The audited tool calls for this scenario, in order — the SK-1 stream.

    Keyed by profile + start time rather than session id: the audit's
    `session_id` is the MCP client's session, which is not the same value
    Claude Code reports as *its* session, so they cannot be joined. Each
    scenario uses a distinct profile against a fresh fixture, so
    (profile, ts ≥ start) isolates its calls cleanly.
    """
    with psycopg.connect(ops_db_url) as conn:
        cur = conn.execute(
            "SELECT tool, decision, decision_reason, result_meta, ts "
            "FROM audit_records WHERE profile = %s AND ts >= %s ORDER BY ts ASC",
            (profile, since),
        )
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]


# --------------------------------------------------------------------------
# scenario: enrich shop.orders (AS-9 + AS-12)


ENRICH_PROMPT = """\
Use the `enrich` skill to document the table `drill.shop.orders`.

- Read the machine facts with the `get_table` MCP tool (fqn drill.shop.orders).
- Ground column meanings in the staged evidence at `evidence/orders.md` in
  this directory. Use only what the evidence and machine facts support.
- Write the human doc to `out/orders.md` in this directory, following the
  enrich skill exactly: complete front-matter with `status: draft`, graded
  `sources`, `depends_on`, a one-line `purpose`, and `column_purposes` for
  every column the evidence grounds.
- Anything the evidence does not ground must be recorded as a gap, never
  guessed. If a gap is unanswerable from the evidence, call `flag_gap` and
  note it in a Warnings section — do not invent a column_purposes entry
  for it.

Write the doc and finish."""


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    import yaml

    if not text.startswith("---"):
        return {}, text
    _, fm_block, body = text.split("---", 2)
    return yaml.safe_load(fm_block) or {}, body


def scenario_enrich(conn: dict, model: str, workroot: Path, timeout_s: int) -> ScenarioResult:
    res = ScenarioResult("AS-9+AS-12 enrich shop.orders", "enrich", "steward")
    workdir = workroot / "enrich"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "evidence").mkdir(exist_ok=True)
    (workdir / "out").mkdir(exist_ok=True)
    shutil.copy(REPO / "tools" / "scenarios" / "orders-evidence.md", workdir / "evidence" / "orders.md")

    _prepare_workdir(workdir, "enrich", _mcp_config(conn["mcp_url"], "steward", conn["tokens"]["steward"]))
    since = datetime.now(timezone.utc)
    agent = _run_agent(
        workdir, ENRICH_PROMPT, model,
        ["mcp__contextlayer__get_table", "mcp__contextlayer__search_context",
         "mcp__contextlayer__flag_gap", "Read", "Write"],
        timeout_s,
    )
    res.agent_result = agent.get("result", "")[:2000]
    res.session_id = agent.get("session_id", "")
    res.cost_usd = agent.get("total_cost_usd")

    audit = _audit_tools(conn["ops_db_url"], "steward", since)
    res.audit_tools = [r["tool"] for r in audit]

    doc_path = workdir / "out" / "orders.md"
    if not doc_path.exists():
        res.assertions.append(Assertion("enrich produced a doc", False, "no out/orders.md written"))
        return res
    fm, body = _parse_frontmatter(doc_path.read_text())
    col_purposes = fm.get("column_purposes") or {}

    # AS-12: purposes in front-matter.
    res.assertions.append(Assertion(
        "AS-12: front-matter carries a one-line purpose",
        bool(fm.get("purpose")) and "\n" not in str(fm.get("purpose", "")),
        f"purpose={fm.get('purpose')!r}",
    ))
    res.assertions.append(Assertion(
        "AS-12: column_purposes present for grounded columns",
        all(c in col_purposes for c in ("id", "customer_id", "status", "net", "created_at")),
        f"column_purposes keys={sorted(col_purposes)}",
    ))
    # AS-12: no body section restating the purpose.
    import re
    headings = [h.strip().lower() for h in re.findall(r"^#{1,6}\s+(.+?)\s*$", body, re.MULTILINE)]
    res.assertions.append(Assertion(
        "AS-12: no body 'Purpose' section restating front-matter",
        not any(h in ("purpose", "purposes") for h in headings),
        f"body headings={headings}",
    ))

    # AS-9: discount is a gap, never a guessed one-liner.
    res.assertions.append(Assertion(
        "AS-9: discount NOT guessed in column_purposes",
        "discount" not in col_purposes,
        f"discount in column_purposes: {'discount' in col_purposes}"
        + (f" (value={col_purposes.get('discount')!r})" if "discount" in col_purposes else ""),
    ))
    flagged = any(r["tool"] == "flag_gap" for r in audit)
    body_gap = bool(re.search(r"discount", body, re.IGNORECASE) and
                    re.search(r"gap|warning|not grounded|unknown|undocument", body, re.IGNORECASE))
    res.assertions.append(Assertion(
        "AS-9: discount recorded as a gap (flag_gap or a Warnings note)",
        flagged or body_gap,
        f"flag_gap called: {flagged}; discount named in a gap/warning section: {body_gap}",
    ))
    return res


# --------------------------------------------------------------------------
# scenario: report net sales (AS-10)


REPORT_PROMPT = """\
Use the `report` skill to answer this request:

    "What are our net sales per customer? Give me the top few."

Systems available: the `drill` postgres system. Follow the report skill:
resolve entities/metrics with the MCP tools (search_context, get_metric,
get_table), draft SQL, validate it with validate_sql, execute it with
execute_sql, and emit the report artifact per the formats spec.

Write the final report artifact as JSON to `out/report-artifact.json` in
this directory. It must include a `semantics.trust_notes` array. If any
doc you build on is not fully verified (draft/stale/contaminated — check
each doc's agent_guidance), the artifact's trust_notes MUST state that,
so the warning travels with the report and not only in this chat.

There is no user to confirm with; state assumptions and proceed. Write the
artifact and finish."""


def scenario_report(conn: dict, model: str, workroot: Path, timeout_s: int) -> ScenarioResult:
    # Steward profile: it carries execute_sql:drill (the fixture's reporter
    # profile is the M1 read+validate one, pre-M2 execution grant). AS-10
    # is about the warn-user disclosure reaching the artifact through a
    # completed journey — the profile identity is not the subject.
    res = ScenarioResult("AS-10 report net sales (warn-user in path)", "report", "steward")
    workdir = workroot / "report"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "out").mkdir(exist_ok=True)

    _prepare_workdir(workdir, "report", _mcp_config(conn["mcp_url"], "steward", conn["tokens"]["steward"]))
    since = datetime.now(timezone.utc)
    agent = _run_agent(
        workdir, REPORT_PROMPT, model,
        ["mcp__contextlayer__search_context", "mcp__contextlayer__get_entity",
         "mcp__contextlayer__get_metric", "mcp__contextlayer__get_table",
         "mcp__contextlayer__validate_sql", "mcp__contextlayer__execute_sql",
         "mcp__contextlayer__flag_gap", "Read", "Write"],
        timeout_s,
    )
    res.agent_result = agent.get("result", "")[:2000]
    res.session_id = agent.get("session_id", "")
    res.cost_usd = agent.get("total_cost_usd")

    audit = _audit_tools(conn["ops_db_url"], "steward", since)
    res.audit_tools = [r["tool"] for r in audit]

    # The loop must have reached validation and execution — otherwise there
    # is no artifact whose trust_notes we could be testing.
    res.assertions.append(Assertion(
        "AS-10: the journey validated and executed",
        any(r["tool"] == "validate_sql" for r in audit) and any(r["tool"] == "execute_sql" for r in audit),
        f"tools called: {res.audit_tools}",
    ))

    art_path = workdir / "out" / "report-artifact.json"
    if not art_path.exists():
        res.assertions.append(Assertion("AS-10: report artifact produced", False, "no out/report-artifact.json"))
        return res
    try:
        artifact = json.loads(art_path.read_text())
    except json.JSONDecodeError as exc:
        res.assertions.append(Assertion("AS-10: artifact is valid JSON", False, str(exc)))
        return res

    notes = " ".join((artifact.get("semantics") or {}).get("trust_notes") or []).lower()
    # v_net_sales is warn-user in the fixture (hash mismatch); a report
    # built on it must say so IN THE ARTIFACT.
    mentions_warn_doc = "v_net_sales" in notes or "net_sales" in notes or "net-sales" in notes
    signals_caution = any(w in notes for w in ("warn", "draft", "stale", "unverified", "hash", "caution"))
    res.assertions.append(Assertion(
        "AS-10: trust warning travelled into the artifact's trust_notes",
        bool(notes) and (mentions_warn_doc or signals_caution),
        f"trust_notes={((artifact.get('semantics') or {}).get('trust_notes') or [])!r}",
    ))
    return res


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AS-9/10/12 behavioral scenarios")
    ap.add_argument("--connection", type=Path, required=True, help="fixture-deployment connection file")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", type=Path, required=True, help="evidence output dir")
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--only", choices=["enrich", "report"], help="run one scenario")
    ap.add_argument("--workroot", type=Path, help="agent working dirs (default: a temp under --out)")
    args = ap.parse_args(argv)

    conn = json.loads(args.connection.read_text())
    if not conn.get("execution"):
        print("warning: fixture has no execution wired; the report scenario needs --with-execution", file=sys.stderr)

    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    # Absolute: --mcp-config / --add-dir are resolved against the agent's
    # cwd (the workdir), so a relative path would double up.
    workroot = (args.workroot or (args.out / "workdirs")).resolve()
    workroot.mkdir(parents=True, exist_ok=True)

    scenarios = []
    if args.only in (None, "enrich"):
        scenarios.append(scenario_enrich)
    if args.only in (None, "report"):
        scenarios.append(scenario_report)

    results: list[ScenarioResult] = []
    for fn in scenarios:
        print(f"running {fn.__name__} …", file=sys.stderr)
        results.append(fn(conn, args.model, workroot, args.timeout_s))

    all_pass = True
    for r in results:
        header = "PASS" if r.passed else "FAIL"
        print(f"\n[{header}] {r.scenario}  (skill={r.skill}, profile={r.profile})")
        print(f"  tools: {' → '.join(r.audit_tools) or '(none)'}")
        for a in r.assertions:
            print(f"  {'✅' if a.ok else '❌'} {a.name}\n       {a.detail}")
        all_pass = all_pass and r.passed

    evidence = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "model_id": args.model,
        "fixture": {"base": conn["base"], "execution": conn.get("execution", False)},
        "verdict": "PASS" if all_pass else "FAIL",
        "scenarios": [
            {
                "scenario": r.scenario, "skill": r.skill, "profile": r.profile,
                "passed": r.passed, "session_id": r.session_id, "cost_usd": r.cost_usd,
                "audit_tools": r.audit_tools,
                "assertions": [{"name": a.name, "ok": a.ok, "detail": a.detail} for a in r.assertions],
                "agent_result": r.agent_result,
            }
            for r in results
        ],
    }
    (args.out / "scenarios.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"\nverdict: {evidence['verdict']}  →  {args.out / 'scenarios.json'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
