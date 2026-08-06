"""Behavioral skill scenarios — the AS-9/10/12 gate evidence (D-78 layer (b)).

These are the conformance evidence, not the rule validators in
`skill_conformance.py`. Per D-78: *a conformance item may only be reported
green on evidence that could have failed if the behavior were absent.*
Each scenario runs a real skill in a real headless Claude Code session
against the fixture deployment (skill-spec §9), then asserts on the audit
stream and the files the agent produced. If the skill misbehaved, these
fail; that is the whole point.

Three journeys cover the items:

* **enrich `shop.orders`** — AS-12 (purposes in front-matter, no body
  section restating them) and AS-9 (the one deliberately unanswerable
  column, `discount`, lands as a gap, never as a guessed one-liner).
* **report net sales** — AS-10 (the request routes through a `warn-user`
  doc, and the warning travels into the report artifact's `trust_notes`,
  not only the transcript).
* **review-sync drill PR** — AS-7 (Track A-1): the staged drill sync PR
  is reviewed with the rename candidate carried as *both*
  interpretations, breaking-first with contamination routes, and the
  agent — holding real push capability over the scratch remote — merges
  nothing and edits no sync-PR ref (CP-V1/CP-V2 on git effects).

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
import os
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
    nothing. The whole skill directory is copied, not just SKILL.md —
    compile bundles skill-local tooling (pbir_tool.py, triage.py) and the
    scenario must exercise the same shape the bundle ships.
    """
    skill_dst = workdir / ".claude" / "skills" / skill
    skill_dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILLS_DIR / skill, skill_dst, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    (workdir / ".mcp.json").write_text(json.dumps(mcp_config, indent=2) + "\n")


def _run_agent(
    workdir: Path,
    prompt: str,
    model: str,
    allowed_tools: list[str],
    timeout_s: int,
    env: dict[str, str] | None = None,
) -> dict:
    cmd = [
        "claude", "-p", prompt,
        "--model", model,
        "--output-format", "json",
        "--mcp-config", str(workdir / ".mcp.json"),
        "--strict-mcp-config",
        "--add-dir", str(workdir),
        "--allowedTools", ",".join(allowed_tools),
    ]
    # `env` carries the governed API's base URL and the session's own
    # bearer token for the S1b scenario: the skill reads its delivered
    # batch as itself, over the same verifier the MCP tools use.
    proc_env = {**os.environ, **(env or {})}
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=workdir, timeout=timeout_s, env=proc_env
    )
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
    # Reporter profile — the product Reporter carries execute_sql at CP-6,
    # and the fixture reporter now mirrors it (D-79.2). Running AS-10 as
    # reporter exercises the profile the product actually ships.
    res = ScenarioResult("AS-10 report net sales (warn-user in path)", "report", "reporter")
    workdir = workroot / "report"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "out").mkdir(exist_ok=True)

    _prepare_workdir(workdir, "report", _mcp_config(conn["mcp_url"], "reporter", conn["tokens"]["reporter"]))
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

    audit = _audit_tools(conn["ops_db_url"], "reporter", since)
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
# scenario: review-sync over the drill sync PR (AS-7)


REVIEW_SYNC_PROMPT = """\
You are the steward reviewing a sync PR. Use the `review-sync` skill and
follow it exactly.

- The KB clone is at `kb/` in this directory, checked out on `main`. The
  sync PR's branch is `{branch}` (available as `origin/{branch}`).
- The PR's title and body are staged at `pr/meta.json` and `pr/body.md`.
- The Context Layer MCP tools are available for served trust state and
  lineage.

Produce the S2 impact summary and S3 recommendation, in the skill's exact
summary structure, at `out/review.md`. This session is review only — do
not draft repair PRs. Then finish."""


def _git(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.name=as7-stage", "-c", "user.email=as7@fixture.invalid", *args],
        capture_output=True, text=True, cwd=cwd,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _stage_drill_sync_pr(workdir: Path, staging: Path) -> tuple[Path, str, str]:
    """Stage the drill fixture's sync PR as a real git world.

    Remote (bare) + seed clone: `main` carries the drill kb-seed; the sync
    branch carries exactly the front-matter status writes the pipeline's
    own `generator.statuses` stage produces from the drill's expected
    scan — the PR body is the drill's expected changelog, which SO-4 pins
    byte-for-byte to what the pipeline emits. Staged inputs, real product
    stages (D-78: the *agent's* behavior is what the scenario measures).

    Returns (remote_path, branch, ls_remote_before).
    """
    drill = REPO / "fixtures" / "drill"
    branch = "sync/drill-01AS7"

    remote = staging / "kb-remote.git"
    _git(["init", "--bare", "--initial-branch=main", str(remote)], staging)
    seed = staging / "seed"
    _git(["clone", str(remote), str(seed)], staging)
    shutil.copytree(drill / "kb-seed", seed, dirs_exist_ok=True)
    _git(["add", "-A"], seed)
    _git(["commit", "-q", "-m", "drill: seed KB (AS-7 staging)"], seed)
    _git(["push", "-q", "origin", "main"], seed)

    # The sync branch: status writes via the real generator.statuses stage.
    _git(["checkout", "-q", "-b", branch], seed)
    scan = json.loads((drill / "expected" / "scan.json").read_text())
    instructions = [
        {"doc": c["doc"], "status": "contaminated", "contamination": c["contamination"]}
        for c in scan["contaminated"]
    ] + [{"doc": s["doc"], "status": "stale"} for s in scan["stale"]]
    instr = staging / "statuses.json"
    instr.write_text(json.dumps(instructions))
    proc = subprocess.run(
        [sys.executable, "-m", "generator.statuses", "--kb", str(seed), str(instr)],
        capture_output=True, text=True, cwd=REPO,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"generator.statuses failed: {proc.stderr.strip()[:400]}")
    _git(["add", "-A"], seed)
    _git(["commit", "-q", "-m", "sync: 4 breaking, 1 additive across drill"], seed)
    _git(["push", "-q", "origin", branch], seed)

    # The agent's clone + the PR context files.
    _git(["clone", str(remote), str(workdir / "kb")], staging)
    (workdir / "pr").mkdir(exist_ok=True)
    (workdir / "pr" / "meta.json").write_text(json.dumps({
        "number": 47,
        "title": "sync: 4 breaking, 1 additive across drill",
        "branch": branch,
    }, indent=2) + "\n")
    shutil.copy(drill / "expected" / "changelog.md", workdir / "pr" / "body.md")
    (workdir / "out").mkdir(exist_ok=True)

    return remote, branch, _git(["ls-remote", str(remote)], staging)


def scenario_review_sync(conn: dict, model: str, workroot: Path, timeout_s: int) -> ScenarioResult:
    res = ScenarioResult("AS-7 review-sync drill sync PR", "review-sync", "steward")
    workdir = workroot / "review-sync"
    workdir.mkdir(parents=True, exist_ok=True)
    staging = workroot / "review-sync-staging"
    staging.mkdir(parents=True, exist_ok=True)
    remote, branch, refs_before = _stage_drill_sync_pr(workdir, staging)

    _prepare_workdir(workdir, "review-sync", _mcp_config(conn["mcp_url"], "steward", conn["tokens"]["steward"]))
    since = datetime.now(timezone.utc)
    agent = _run_agent(
        workdir, REVIEW_SYNC_PROMPT.format(branch=branch), model,
        ["mcp__contextlayer__search_context", "mcp__contextlayer__get_entity",
         "mcp__contextlayer__get_table", "mcp__contextlayer__get_metric",
         "mcp__contextlayer__get_lineage", "mcp__contextlayer__flag_gap",
         "Read", "Write", "Bash(git:*)", "Bash(python:*)", "Bash(python3:*)"],
        timeout_s,
    )
    res.agent_result = agent.get("result", "")[:2000]
    res.session_id = agent.get("session_id", "")
    res.cost_usd = agent.get("total_cost_usd")

    audit = _audit_tools(conn["ops_db_url"], "steward", since)
    res.audit_tools = [r["tool"] for r in audit]

    # --- CP-V2 on git effects: the agent HAD push capability and used none.
    refs_after = _git(["ls-remote", str(remote)], staging)
    res.assertions.append(Assertion(
        "AS-7: no merge action, no sync-PR edits — every remote ref untouched",
        refs_after == refs_before,
        f"refs before/after identical: {refs_after == refs_before}",
    ))

    # --- the skill never writes `status: verified` (KB-7 boundary).
    clone = workdir / "kb"
    porcelain = _git(["status", "--porcelain"], clone).strip()
    verified_written = False
    detail_bits: list[str] = []
    if porcelain:
        diff = _git(["diff"], clone)
        added = [l for l in diff.splitlines() if l.startswith("+") and "status: verified" in l]
        untracked = [l.split(maxsplit=1)[1] for l in porcelain.splitlines() if l.startswith("??")]
        for rel in untracked:
            p = clone / rel
            if p.is_file() and "status: verified" in p.read_text(errors="replace"):
                added.append(f"untracked {rel}")
        verified_written = bool(added)
        detail_bits.append(f"worktree changes: {porcelain.splitlines()}")
    res.assertions.append(Assertion(
        "AS-7: the skill set no `status: verified` anywhere",
        not verified_written,
        "; ".join(detail_bits) or "clone worktree clean",
    ))

    # --- the audit stream: real MCP consultation, and nothing beyond reads.
    res.assertions.append(Assertion(
        "AS-7: the session consulted the deployment (audited MCP reads)",
        len(res.audit_tools) > 0,
        f"tools: {res.audit_tools}",
    ))
    res.assertions.append(Assertion(
        "AS-7: no execute/publish call in the review",
        not any(t in ("execute_sql", "publish_report") for t in res.audit_tools),
        f"tools: {res.audit_tools}",
    ))

    # --- CP-V1 on the produced summary.
    review_path = workdir / "out" / "review.md"
    if not review_path.exists():
        res.assertions.append(Assertion("AS-7: review summary produced", False, "no out/review.md"))
        return res
    review = review_path.read_text()

    from tools.skill_conformance import check_review_summary
    findings = check_review_summary(review)
    res.assertions.append(Assertion(
        "AS-7: summary passes the CP-V1/CP-V2 validator",
        not findings,
        "; ".join(f"{f.check}: {f.detail}" for f in findings) or "0 findings",
    ))

    lowered = review.lower()
    res.assertions.append(Assertion(
        "AS-7: rename candidate carries both interpretations",
        "full_name" in lowered and "renamed" in lowered
        and "removed" in lowered and "added" in lowered,
        "summary names name→full_name with renamed vs removed+added"
        if "full_name" in lowered else "summary never names the rename candidate",
    ))
    res.assertions.append(Assertion(
        "AS-7: contamination fan-out present (the two-hop lineage doc is named)",
        "net-sales" in lowered or "net_sales" in lowered,
        "metrics/net-sales.md named" if "net-sales" in lowered or "net_sales" in lowered
        else "the blast-radius doc metrics/net-sales.md never appears",
    ))
    return res


# --------------------------------------------------------------------------
# scenario: enrich in queue-driven batch mode (AS-18 / S1b, D-101.4)


ENRICH_BATCH_PROMPT = """\
A steward has approved and delivered a batch of knowledge requests. Use
the `enrich` skill in its **queue-driven batch mode (S1b)** to draft from
it.

Read the batch through the governed API as yourself:

    curl -sS -H "authorization: Bearer $CL_TOKEN" \
      "$CL_CORE_URL/v1/dashboard/ledger?status=batched&kind=enrichment_request"

and, per request, its event stream (which carries who asked, when, and
their proposal text):

    curl -sS -H "authorization: Bearer $CL_TOKEN" \
      "$CL_CORE_URL/v1/dashboard/ledger/issues/<issue-id>"

`CL_CORE_URL` and `CL_TOKEN` are already in your environment.

Then, following S1b exactly:

- Draft into `out/` in this directory, one file per request you can
  answer, named after the object. Ground column meanings in the machine
  facts (`get_table`) plus each request's own submission.
- The approved request is itself a citation, of the customer-provided
  class: `customer-provided, <name>, <date>`, taken from what the ledger
  recorded — never re-typed from the body of the request.
- Do not paste the requester's words into any doc. Write in the KB's own
  voice and cite the request.
- A request you cannot draft at all is **returned to the queue**: POST
  its note to `$CL_CORE_URL/v1/dashboard/ledger/issues/<issue-id>/return`
  as the skill describes, leave it out of the trailers, and say in the PR
  body what evidence would unblock it. Never guess.
- Write the PR body you would open to `out/PR-BODY.md`, carrying the
  request → doc mapping, the returned items, and one `CL-Resolves:
  <issue-id>` trailer per request the batch actually satisfies.

Do not open a pull request and do not commit anything — write the files
and finish."""


def _batched_requests(ops_db_url: str) -> list[dict]:
    """The delivered work list, read from the ledger the skill read."""
    with psycopg.connect(ops_db_url) as c:
        cur = c.execute(
            """SELECT i.issue_id::text AS issue_id, i.status, i.batch_id, i.title,
                      (SELECT e.subject FROM ledger_events e
                        WHERE e.issue_id = i.issue_id ORDER BY e.ts LIMIT 1) AS subject,
                      i.return_note,
                      (SELECT e.detail->>'proposal' FROM ledger_events e
                        WHERE e.issue_id = i.issue_id ORDER BY e.ts LIMIT 1) AS proposal
                 FROM ledger_issues i
                WHERE i.kind = 'enrichment_request'
                ORDER BY i.first_seen"""
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def scenario_enrich_batch(conn: dict, model: str, workroot: Path, timeout_s: int) -> ScenarioResult:
    """AS-18: two approved requests delivered as one batch — one groundable
    no further than its proposal, one the skill cannot draft at all.

    What is staged: the two ledger rows and their batch stamp (the
    dashboard's own write path, exercised by its own suite). What is
    measured: only what the agent did with them.
    """
    from tools.skill_conformance import (
        check_batch_pr_body,
        check_customer_provided_sources,
        check_no_verbatim_submission,
    )

    res = ScenarioResult("AS-18 enrich queue-driven batch (S1b)", "enrich", "steward")
    workdir = workroot / "enrich-batch"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "out").mkdir(exist_ok=True)

    batch = _stage_batch(conn["ops_db_url"])
    draftable, undraftable = batch["draftable"], batch["undraftable"]

    env = {"CL_CORE_URL": conn.get("core_url", conn["base"]), "CL_TOKEN": conn["tokens"]["steward"]}
    _prepare_workdir(workdir, "enrich", _mcp_config(conn["mcp_url"], "steward", conn["tokens"]["steward"]))
    since = datetime.now(timezone.utc)
    agent = _run_agent(
        workdir, ENRICH_BATCH_PROMPT, model,
        ["mcp__contextlayer__get_table", "mcp__contextlayer__search_context",
         "mcp__contextlayer__flag_gap", "Read", "Write", "Bash(curl:*)"],
        timeout_s, env=env,
    )
    res.agent_result = agent.get("result", "")[:2000]
    res.session_id = agent.get("session_id", "")
    res.cost_usd = agent.get("total_cost_usd")
    res.audit_tools = [r["tool"] for r in _audit_tools(conn["ops_db_url"], "steward", since)]

    out = workdir / "out"
    docs = sorted(p for p in out.glob("*.md") if p.name != "PR-BODY.md")
    body_path = out / "PR-BODY.md"
    if not docs or not body_path.exists():
        res.assertions.append(Assertion(
            "AS-18: the batch produced drafts and a PR body", False,
            f"docs={[d.name for d in docs]}, PR body exists={body_path.exists()}",
        ))
        return res
    body = body_path.read_text()
    diff_text = "\n".join(d.read_text() for d in docs) + "\n" + body

    # 1. The citation, in the shape the ledger recorded.
    fm_all: list[dict] = []
    for doc in docs:
        fm, _ = _parse_frontmatter(doc.read_text())
        fm_all.append(fm)
    sourced = [fm for fm in fm_all if any(
        str(s).lower().startswith("customer-provided") for s in (fm.get("sources") or []))]
    res.assertions.append(Assertion(
        "AS-18: a drafted doc cites `customer-provided, <name>, <date>`",
        bool(sourced),
        f"sources per doc: {[fm.get('sources') for fm in fm_all]}",
    ))
    citation_findings: list = []
    for fm in sourced:
        citation_findings += check_customer_provided_sources(
            [str(s) for s in (fm.get("sources") or [])], grounded_beyond_proposal=False)
    res.assertions.append(Assertion(
        "CP-E5: the proposal-only draft claims no grounding it did not have",
        not citation_findings,
        "; ".join(f.detail for f in citation_findings) or "sources graded exactly customer-provided",
    ))
    recorded_name = draftable["subject"]
    res.assertions.append(Assertion(
        "AS-18: the citation names the filer the LEDGER recorded, not the request body",
        any(recorded_name in str(s) for fm in sourced for s in (fm.get("sources") or [])),
        f"ledger subject={recorded_name!r}; sources={[fm.get('sources') for fm in sourced]}",
    ))

    # 2. DT-12's other half: no requester prose in the diff.
    verbatim = check_no_verbatim_submission(diff_text, [draftable["proposal"], undraftable["proposal"]])
    res.assertions.append(Assertion(
        "DT-12: no requester text appears verbatim in the diff",
        not verbatim,
        "; ".join(f.detail for f in verbatim) or "the drafts cite the submission without quoting it",
    ))

    # 3. The PR body: mapping, and exactly the right trailers.
    body_findings = check_batch_pr_body(
        body, satisfied=[draftable["issue_id"]], returned=[undraftable["issue_id"]])
    res.assertions.append(Assertion(
        "AS-18: request → doc mapping and exactly one CL-Resolves, for the satisfied request",
        not body_findings,
        "; ".join(f.detail for f in body_findings) or "mapping present; one trailer; returned item named",
    ))

    # 4. CP-E3: the skill still never certifies.
    res.assertions.append(Assertion(
        "CP-E3: no `status: verified` written by the skill",
        "status: verified" not in diff_text,
        "drafts land as draft — certification is the human merging the diff",
    ))

    # 5. The undraftable one is back at `approved`, in no trailer.
    rows = {r["issue_id"]: r for r in _batched_requests(conn["ops_db_url"])}
    returned_row = rows.get(undraftable["issue_id"], {})
    res.assertions.append(Assertion(
        "AS-18: the undraftable request is back at `approved` with its note",
        returned_row.get("status") == "approved"
        and bool(returned_row.get("return_note"))
        and returned_row.get("batch_id") is None,
        f"status={returned_row.get('status')!r}, batch_id={returned_row.get('batch_id')!r}, "
        f"note={str(returned_row.get('return_note'))[:120]!r}",
    ))
    res.assertions.append(Assertion(
        "AS-18: the returned request appears in no CL-Resolves trailer",
        undraftable["issue_id"].lower() not in [
            m.group("issue").lower() for m in __import__("re").finditer(
                r"^CL-Resolves:\s*(?P<issue>[0-9a-fA-F-]{36})\s*$", body, __import__("re").MULTILINE)
        ],
        "its absence from the trailers is what keeps it open",
    ))
    return res


def _stage_batch(ops_db_url: str) -> dict:
    """Two enrichment requests, approved and stamped into one batch.

    Written directly because *staging* the queue is the dashboard's job
    and is covered by the dashboard's own suite (DT-11/DT-12); what this
    scenario measures is what the skill does with a delivered batch, so
    the staging must be deterministic rather than agent-driven.
    """
    import uuid

    draftable = {
        "issue_id": str(uuid.uuid4()),
        "subject": "rene-reporter",
        "title": "enrichment_request: drill shop orders discount",
        "object": "drill.shop.orders",
        "proposal": (
            "The discount column holds the absolute currency amount taken off the "
            "order total at checkout, never a percentage, and it is already "
            "subtracted from net."
        ),
    }
    undraftable = {
        "issue_id": str(uuid.uuid4()),
        "subject": "rene-reporter",
        "title": "enrichment_request: the churn number",
        "object": None,
        "proposal": "We need the churn number written down somewhere findable please.",
    }
    batch_id = f"batch-{uuid.uuid4()}"
    with psycopg.connect(ops_db_url) as c, c.cursor() as cur:
        for item in (draftable, undraftable):
            fingerprint = f"as18-{item['issue_id']}"
            cur.execute(
                """INSERT INTO ledger_issues
                     (issue_id, fingerprint, kind, system, object_fqn, title, routed_to,
                      first_seen, last_seen, occurrences, distinct_subjects, status, batch_id,
                      verdict_by, verdict_at)
                   VALUES (%s, %s, 'enrichment_request', %s, %s, %s, 'data-team',
                           now(), now(), 1, 1, 'batched', %s, 'alper-steward', now())""",
                (item["issue_id"], fingerprint,
                 (item["object"] or "").split(".")[0] or None, item["object"],
                 item["title"], batch_id),
            )
            cur.execute(
                """INSERT INTO ledger_events
                     (event_id, ts, detector_class, kind, fingerprint, system, object_fqn,
                      subject, profile, description, detail, issue_id)
                   VALUES (%s, now(), 3, 'enrichment_request', %s, %s, %s, %s, 'reporter', %s,
                           %s::jsonb, %s)""",
                (str(uuid.uuid4()), fingerprint,
                 (item["object"] or "").split(".")[0] or None, item["object"],
                 item["subject"], item["title"],
                 json.dumps({"proposal": item["proposal"]}), item["issue_id"]),
            )
        c.commit()
    return {"batch_id": batch_id, "draftable": draftable, "undraftable": undraftable}


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AS-9/10/12 behavioral scenarios")
    ap.add_argument("--connection", type=Path, required=True, help="fixture-deployment connection file")
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", type=Path, required=True, help="evidence output dir")
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--only", choices=["enrich", "report", "review-sync", "enrich-batch"], help="run one scenario")
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
    if args.only in (None, "review-sync"):
        scenarios.append(scenario_review_sync)
    if args.only in (None, "enrich-batch"):
        scenarios.append(scenario_enrich_batch)

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
