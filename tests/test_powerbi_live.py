"""Phase-2 step 8 — LIVE verification of the Power BI leg (D-91 gate prep).

Env-gated like every live suite: the default run skips; with the gate
set, this drives the REAL external boundary the fixtures cannot prove —
push-dataset creation in the configured workspace, Fabric deploy of a real
PBIR, the RA-7 read-back against the real service, and the AT-6
revision semantics live. Data comes from a task-7.0 reporting view
through the real Postgres executor under the execution role (RA-2's
shape: gateway-grade guardrails, QE-5 encoding; the full MCP-server
path is fixture-proven and demo'd at the gate).

    CTXLAYER_POWERBI_LIVE=1 CTXLAYER_PG_EXEC_DSN=postgres://… \
      .venv/bin/python -m pytest tests/test_powerbi_live.py -v -s

Reads .secrets/powerbi.env for the SP credential (never echoed).
Evidence lands in results/cp7-powerbi-live/evidence.json — committed,
because only live runs pass gates and evidence is what passing looks
like. The artifact id is FIXED so re-runs revise the same model and
report (RA-8) instead of littering the workspace.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from connectors.powerbi.config import load_powerbi_env
from connectors.powerbi.publisher import PowerBIPublisher, dataset_name
from connectors.sdk.providers import Identity, PublishRequest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "core" / "skills" / "report" / "pbir_tool.py"
EVIDENCE_DIR = REPO / "results" / "cp7-powerbi-live"
ARTIFACT_ID = "ra-live-powerbi-jobs-0001"
FLAGS = {
    "create_report": "api", "create_dataset": "yes", "sql_backing": "views",
    "cross_source": "native", "scheduled_refresh": "no", "git_integration": "no",
}

IDENTITY = Identity(
    subject="oidc|live-test",
    roles=("reporter",),
    session_id="s-powerbi-live",
    intent="CP-7 step 8 live verification",
)

pytestmark = [
    pytest.mark.powerbi_live,
    pytest.mark.skipif(
        not os.environ.get("CTXLAYER_POWERBI_LIVE"),
        reason="set CTXLAYER_POWERBI_LIVE=1, CTXLAYER_PG_EXEC_DSN, and fill .secrets/powerbi.env",
    ),
]

STATEMENT = (
    "SELECT status, job_count, distinct_users, first_created, last_created "
    "FROM reporting.v_jobs_by_status ORDER BY status"
)


def artifact(layout_revision: int = 1) -> dict:
    visuals = [{
        "kind": "bar", "registry_kind": "bar", "table": "jobs_by_status",
        "x": "status", "y": "job_count",
        "title": "Job applications by status",
        "notes": "bars not line: status is categorical, no calendar spine",
    }]
    if layout_revision >= 2:
        visuals.append({
            "kind": "table", "registry_kind": "table", "table": "jobs_by_status",
            "columns": ["status", "job_count", "distinct_users"],
            "title": "Status detail",
        })
    return {
        "artifact_version": "1",
        "id": ARTIFACT_ID,
        "title": "Jobs by status (live step-8 evidence)",
        "kb_ref": "live",
        "queries": [{
            "name": "jobs_by_status",
            "system": "supabase",
            "request": {"dialect": "sql", "statement": STATEMENT},
            "validated_against": "sha256:live-step8",
            "backing": {"mode": "reporting_view", "ref": "reporting.v_jobs_by_status"},
        }],
        "semantics": {
            "metrics": [], "dimensions": [], "grain": "status",
            "trust_notes": [
                "data from reporting.v_jobs_by_status (task 7.0 exec-role view; "
                "counts of 1-2 may be personal — small-cell caveat per the view header)",
            ],
        },
        "layout": {
            "designed_by": "report-skill@step8-live",
            "pages": [{"name": "Overview", "visuals": visuals}],
            "trust_element": {"page": "Overview", "placement": "footer",
                              "content_from": "trust_notes"},
        },
        "blend": None,
    }


def execute_view() -> dict:
    from connectors.postgres.executor import PostgresExecutor
    from connectors.sdk import ExecuteRequest, Guardrails

    executor = PostgresExecutor()
    config = {
        "system": "supabase", "mode": "live",
        "execute_dsn": os.environ["CTXLAYER_PG_EXEC_DSN"],
    }
    executor.preflight(config)  # G3: the role really is read-only
    result = executor.execute(
        config,
        ExecuteRequest.parse({"dialect": "sql", "statement": STATEMENT, "params": []}),
        Guardrails.parse({"row_cap": 50000, "timeout_s": 60,
                          "statement_class": "select-only",
                          "validated_against": "sha256:live-step8"}),
        IDENTITY,
    )
    payload = result.to_json()
    assert payload["truncated"] is False
    assert payload["row_count"] >= 1
    return payload


def publisher_config(env) -> dict:
    os.environ["CTXLAYER_POWERBI_SECRET"] = env.client_secret
    return {
        "system": "powerbi",
        "tenant_id": env.tenant_id,
        "client_id": env.client_id,
        "workspace_id": env.workspace_id,
        "client_secret_env": "CTXLAYER_POWERBI_SECRET",
    }


def run_tool(args: list[str], env) -> dict:
    process = subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "POWERBI_TENANT_ID": env.tenant_id,
            "POWERBI_CLIENT_ID": env.client_id,
            "POWERBI_CLIENT_SECRET": env.client_secret,
        },
    )
    assert process.returncode == 0, f"pbir_tool {args[0]} failed: {process.stderr[-2000:]}"
    return json.loads(process.stdout)


def test_step8_live_deliver_author_verify_attest_and_revise(tmp_path):
    env = load_powerbi_env(REPO / ".secrets" / "powerbi.env")
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    evidence: dict = {
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace_id": env.workspace_id,
        "artifact_id": ARTIFACT_ID,
        "view": "reporting.v_jobs_by_status",
    }
    publisher = PowerBIPublisher()
    config = publisher_config(env)

    # --- act 1: deliver a real model from real view rows -------------------
    result_payload = execute_view()
    evidence["rows_executed"] = result_payload["row_count"]
    deliver1 = publisher.publish(
        config,
        PublishRequest.parse(artifact(), "powerbi", "deliver_model",
                             {"jobs_by_status": result_payload}),
        IDENTITY, FLAGS,
    )
    delivered = deliver1.detail["delivered"]
    evidence["dataset"] = {
        "name": deliver1.detail["dataset_name"],
        "id": delivered["dataset_id"],
        "url": deliver1.created[0]["url"],
        "tables": delivered["tables"],
    }
    assert deliver1.pending_human_steps == []
    assert deliver1.detail["dataset_name"] == dataset_name(ARTIFACT_ID)

    # --- act 2: author, deploy, verify, attest -----------------------------
    artifact_file = tmp_path / "artifact.json"
    delivered_file = tmp_path / "delivered.json"
    parts = tmp_path / "parts"
    artifact_file.write_text(json.dumps(artifact()), encoding="utf-8")
    delivered_file.write_text(json.dumps(delivered), encoding="utf-8")
    generated = run_tool([
        "generate", "--artifact", str(artifact_file), "--delivered", str(delivered_file),
        "--out", str(parts), "--generated-date", time.strftime("%Y-%m-%d"),
    ], env)

    report_id_file = EVIDENCE_DIR / "report_id.txt"
    deploy_args = ["deploy", "--parts", str(parts), "--workspace", env.workspace_id,
                   "--display-name", "Jobs by status (Context Layer step-8)"]
    if report_id_file.exists():
        deploy_args += ["--report-id", report_id_file.read_text().strip()]
    deployed = run_tool(deploy_args, env)
    report_id = deployed["report_id"]
    report_id_file.write_text(report_id + "\n", encoding="utf-8")

    verdict = run_tool([
        "verify", "--parts", str(parts), "--workspace", env.workspace_id,
        "--report-id", report_id, "--delivered", str(delivered_file),
    ], env)
    assert verdict["verified"] is True, verdict
    evidence["report"] = {
        "id": report_id,
        "deploy_action": deployed["action"],
        "definition_hash": verdict["definition_hash"],
    }

    attest1 = publisher.publish(
        config,
        PublishRequest.parse(artifact(), "powerbi", "attest", None, None, {
            "report_id": report_id, "definition_hash": verdict["definition_hash"],
        }),
        IDENTITY, FLAGS,
    )
    evidence["report"]["url"] = attest1.created[0]["url"]
    assert attest1.pending_human_steps == []

    # --- act 3: AT-6 live — data-only re-push, definition untouched --------
    repush_payload = execute_view()
    deliver2 = publisher.publish(
        config,
        PublishRequest.parse(artifact(), "powerbi", "deliver_model",
                             {"jobs_by_status": repush_payload},
                             {"jobs_by_status": result_payload}),
        IDENTITY, FLAGS,
    )
    assert deliver2.detail["delivered"]["dataset_id"] == delivered["dataset_id"]
    verdict_after_repush = run_tool([
        "verify", "--parts", str(parts), "--workspace", env.workspace_id,
        "--report-id", report_id, "--delivered", str(delivered_file),
    ], env)
    assert verdict_after_repush["verified"] is True
    assert verdict_after_repush["deployed_hash"] == verdict["definition_hash"]
    evidence["at6_data_only"] = {
        "same_dataset_id": True,
        "definition_hash_unchanged": True,
        "rows_repushed": repush_payload["row_count"],
    }

    # --- act 4: AT-6 live — layout change updates the SAME report_id -------
    artifact_file.write_text(json.dumps(artifact(layout_revision=2)), encoding="utf-8")
    parts2 = tmp_path / "parts2"
    generated2 = run_tool([
        "generate", "--artifact", str(artifact_file), "--delivered", str(delivered_file),
        "--out", str(parts2), "--generated-date", time.strftime("%Y-%m-%d"),
    ], env)
    assert generated2["pbir_hash"] != generated["pbir_hash"]
    redeployed = run_tool([
        "deploy", "--parts", str(parts2), "--workspace", env.workspace_id,
        "--report-id", report_id,
    ], env)
    assert redeployed == {"report_id": report_id, "action": "updated"}
    verdict2 = run_tool([
        "verify", "--parts", str(parts2), "--workspace", env.workspace_id,
        "--report-id", report_id, "--delivered", str(delivered_file),
    ], env)
    assert verdict2["verified"] is True
    attest2 = publisher.publish(
        config,
        PublishRequest.parse(artifact(layout_revision=2), "powerbi", "attest", None, None, {
            "report_id": report_id, "definition_hash": verdict2["definition_hash"],
        }),
        IDENTITY, FLAGS,
    )
    evidence["at6_layout_change"] = {
        "same_report_id": True,
        "new_definition_hash": verdict2["definition_hash"],
        "url": attest2.created[0]["url"],
    }

    evidence["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    evidence["verdict"] = "PASS"
    (EVIDENCE_DIR / "evidence.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8",
    )
    print(f"\nstep-8 evidence written: {EVIDENCE_DIR / 'evidence.json'}")
    print(f"report: {attest2.created[0]['url']}")
