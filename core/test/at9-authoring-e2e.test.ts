/**
 * AT-9 (report-authoring §11): fixture end-to-end — request → deliver →
 * author → deploy → verify → attest, against a fixture workspace and a
 * stubbed Fabric API, with BOTH publish_report calls visible in audit.
 *
 * The pieces are all real: the MCP server and its gates, the gateway
 * execute path (scripted runner answering with a faithful §6 result),
 * the §8.2-amended publish payloads (scripted powerbi runner), and the
 * actual skill-local pbir_tool.py (spawned with the repo python)
 * generating, deploying to, and verifying against an in-test Fabric
 * stub. What is stubbed is exactly Microsoft — which is what "fixture
 * workspace/stubbed Fabric + push APIs" means.
 *
 * AT-10 rides at the end: the compiled reporter bundle (which now
 * carries pbir_tool.py) holds no DB credential material — the
 * session-side credential canary.
 */

import { execFile } from "node:child_process";
import { createServer, type Server } from "node:http";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { compileProfile, writeSetup } from "../src/compile.js";
import { upsertSyncSystem } from "../src/triggers.js";
import { WireClient } from "./fake-runner.js";
import { pythonPath, repoRoot, TEST_TOKEN } from "./helpers.js";
import { auditRows, callTool, setupMcpRig, type McpRig } from "./mcp-helpers.js";

const execFileAsync = promisify(execFile);

const WORKSPACE = "11111111-1111-4111-8111-111111111111";
const TOOL = path.join(repoRoot(), "core", "skills", "report", "pbir_tool.py");

let rig: McpRig;
let drillPin: string;
let fabric: Server;
let fabricBase: string;
const fabricReports = new Map<string, unknown>();

beforeAll(async () => {
  rig = await setupMcpRig();
  drillPin = `sha256:${rig.drill.verdict.canonical_body_sha256.replace(/^sha256:/, "")}`;
  await upsertSyncSystem(rig.core.pool, {
    system: "powerbi",
    connector_name: "powerbi",
    version_constraint: ">=0.1 <0.2",
    payload: {
      config: {
        system: "powerbi",
        tenant_id: "aaaabbbb-0000-cccc-1111-dddd2222eeee",
        client_id: "00001111-aaaa-2222-bbbb-3333cccc4444",
        workspace_id: WORKSPACE,
      },
      credentials: [
        { ref: "env://POWERBI_CLIENT_SECRET", key: "client_secret", required_for: ["publish"] },
      ],
      publish: {
        flags: {
          create_report: "api", create_dataset: "yes", sql_backing: "views",
          cross_source: "native", scheduled_refresh: "no", git_integration: "no",
        },
      },
    },
  });
  await upsertSyncSystem(rig.core.pool, {
    system: "drill",
    connector_name: "postgres",
    version_constraint: ">=0.2 <0.3",
    payload: {
      config: { system: "drill", mode: "live" },
      credentials: [{ ref: "env://CL_EXEC_DSN", key: "execute_dsn", required_for: ["query"] }],
    },
  });

  // The stubbed Fabric surface, serving exactly the pinned path shapes.
  fabric = createServer((request, response) => {
    let raw = "";
    request.on("data", (chunk) => { raw += chunk; });
    request.on("end", () => {
      const body = raw ? JSON.parse(raw) : {};
      const reply = (status: number, payload: unknown) => {
        const data = JSON.stringify(payload);
        response.writeHead(status, { "content-type": "application/json" });
        response.end(data);
      };
      const url = request.url ?? "";
      if (url === `/workspaces/${WORKSPACE}/reports` && request.method === "POST") {
        const id = "5b218778-e7a5-4d73-8187-f10824047715";
        fabricReports.set(id, body.definition);
        reply(201, { id, displayName: body.displayName, type: "Report", workspaceId: WORKSPACE });
      } else if (url.endsWith("/updateDefinition") && request.method === "POST") {
        const id = url.split("/reports/")[1]!.split("/")[0]!;
        fabricReports.set(id, body.definition);
        reply(200, {});
      } else if (url.endsWith("/getDefinition") && request.method === "POST") {
        const id = url.split("/reports/")[1]!.split("/")[0]!;
        reply(200, { definition: fabricReports.get(id) ?? { parts: [] } });
      } else {
        reply(404, { errorCode: "NotFound" });
      }
    });
  });
  await new Promise<void>((resolve) => fabric.listen(0, "127.0.0.1", resolve));
  const address = fabric.address();
  fabricBase = `http://127.0.0.1:${typeof address === "object" && address ? address.port : 0}`;
}, 240_000);

afterAll(async () => {
  await new Promise<void>((resolve) => fabric.close(() => resolve()));
  await rig.stop();
});

function artifact(): Record<string, unknown> {
  return {
    artifact_version: "1",
    id: "ra-at9-0001",
    title: "Net sales by customer",
    kb_ref: "fixture",
    queries: [
      {
        name: "net_sales",
        system: "drill",
        request: {
          dialect: "sql",
          statement: "SELECT customer_id, net_total FROM reporting.v_net_sales",
        },
        validated_against: drillPin,
        backing: { mode: "reporting_view", ref: "reporting.v_net_sales" },
      },
    ],
    semantics: {
      metrics: [{ column: "net_total", ref: "metrics/net-sales.md", certified: true }],
      dimensions: [{ column: "customer_id", ref: "entities/customer.md" }],
      grain: "customer",
      trust_notes: ["built on the fixture drill snapshot"],
    },
    layout: {
      designed_by: "report-skill@at9",
      pages: [{
        name: "Overview",
        visuals: [{
          kind: "bar", registry_kind: "bar", table: "net_sales",
          x: "customer_id", y: "net_total",
          title: "Net sales by customer",
          notes: "bars not line: no calendar spine in backing view",
        }],
      }],
      trust_element: { page: "Overview", placement: "footer", content_from: "trust_notes" },
    },
    blend: null,
  };
}

async function serviceJobs(publishJobs: number): Promise<void> {
  const client = new WireClient(rig.base, TEST_TOKEN);
  const deadline = Date.now() + 60_000;
  let completed = 0;
  while (completed < publishJobs) {
    if (Date.now() > deadline) throw new Error(`serviced ${completed}/${publishJobs} in 60s`);
    const { status, json } = await client.claim({
      runner_id: "at9-runner",
      connectors: [
        { name: "postgres", version: "0.2.5", types: ["execute"] },
        { name: "powerbi", version: "0.1.0", types: ["publish"] },
      ],
      classes: ["interactive"],
      wait_s: 2,
    });
    if (status !== 200) continue;
    const jobId = json.job_id as string;
    const lease = (json.lease as { token: string }).token;
    await client.start(jobId, lease);
    if (json.type === "execute") {
      await client.completeRaw(jobId, lease, JSON.stringify({
        columns: [
          { name: "customer_id", type: "int4" },
          { name: "net_total", type: "numeric" },
        ],
        rows: [[1, "10.50"], [2, "20.25"]],
        row_count: 2, truncated: false, duration_ms: 3,
        source: { executed_on: "replica", engine_version: "fixture" },
      }));
      continue;
    }
    const payload = (json.payload ?? {}) as Record<string, unknown>;
    const mode = payload.mode as string;
    const result = mode === "deliver_model"
      ? {
          mode,
          created: [{ type: "dataset", id: "ds-at9-0001", url: "" }],
          pending_human_steps: [],
          backing: [{ type: "reporting_view", ref: "reporting.v_net_sales" }],
          detail: {
            dataset_name: "cl-at90001",
            delivered: {
              workspace_id: WORKSPACE,
              dataset_id: "ds-at9-0001",
              tables: Object.entries(payload.results as Record<string, Record<string, unknown>>)
                .map(([name, r]) => ({
                  name,
                  columns: ((r.columns ?? []) as { name: string; type: string }[]).map((c) => ({
                    name: c.name,
                    type: c.type === "numeric" ? "Double" : "Int64",
                    source_type: c.type,
                  })),
                  rows_delivered: (r.rows as unknown[]).length,
                })),
            },
          },
        }
      : {
          mode,
          created: [{
            type: "report",
            id: (payload.attestation as { report_id: string }).report_id,
            url: `https://app.powerbi.com/groups/${WORKSPACE}/reports/${(payload.attestation as { report_id: string }).report_id}`,
          }],
          pending_human_steps: [],
          backing: [],
          detail: { attested: payload.attestation },
        };
    const done = await client.completeRaw(jobId, lease, JSON.stringify(result));
    if (done.status !== 200) throw new Error(`delivery rejected: ${JSON.stringify(done.json)}`);
    completed += 1;
  }
}

function runTool(args: string[]): Promise<{ stdout: string; stderr: string }> {
  return execFileAsync(pythonPath(), [TOOL, ...args], {
    env: {
      PATH: process.env.PATH ?? "",
      PBIR_FABRIC_BASE_OVERRIDE: fabricBase,
      POWERBI_FABRIC_TOKEN: "stub-token",
    },
  });
}

describe("AT-9 — the full authoring pipeline against the fixture", () => {
  it("request → deliver → author → deploy → verify → attest; both calls audited; steps empty", async () => {
    const work = await mkdtemp(path.join(tmpdir(), "at9-"));
    const art = artifact();

    // Stage 5: deliver_model through the MCP server.
    const [deliver] = await Promise.all([
      callTool(rig, rig.token("reporter"), "reporter", "publish_report", {
        artifact: art, target: "powerbi", mode: "deliver_model",
      }),
      serviceJobs(1),
    ]);
    expect(deliver.isError).toBeFalsy();
    expect(deliver.payload.pending_human_steps).toEqual([]);
    const delivered = (deliver.payload.detail as Record<string, unknown>).delivered;

    // Stage 6: author with the real skill tool, against the RETURNED schema.
    await writeFile(path.join(work, "artifact.json"), JSON.stringify(art));
    await writeFile(path.join(work, "delivered.json"), JSON.stringify(delivered));
    const parts = path.join(work, "parts");
    const generated = await runTool([
      "generate", "--artifact", path.join(work, "artifact.json"),
      "--delivered", path.join(work, "delivered.json"),
      "--out", parts, "--generated-date", "2026-07-29",
    ]);
    const pbirHash = (JSON.parse(generated.stdout) as { pbir_hash: string }).pbir_hash;

    // Stage 7: deploy to the (stubbed) Fabric workspace.
    const deployed = await runTool([
      "deploy", "--parts", parts, "--workspace", WORKSPACE,
      "--display-name", "Net sales by customer",
    ]);
    const reportId = (JSON.parse(deployed.stdout) as { report_id: string }).report_id;

    // Stage 8: verify — read-back equality + field resolution (RA-7).
    const verified = await runTool([
      "verify", "--parts", parts, "--workspace", WORKSPACE,
      "--report-id", reportId, "--delivered", path.join(work, "delivered.json"),
    ]);
    const verdict = JSON.parse(verified.stdout) as { verified: boolean; definition_hash: string };
    expect(verdict.verified).toBe(true);
    expect(verdict.definition_hash).toBe(pbirHash);

    // Stage 9: attest with the verified hash; layout carries it too.
    const attestArtifact = {
      ...art,
      layout: { ...(art.layout as Record<string, unknown>), pbir_hash: verdict.definition_hash },
    };
    const [attest] = await Promise.all([
      callTool(rig, rig.token("reporter"), "reporter", "publish_report", {
        artifact: attestArtifact, target: "powerbi", mode: "attest",
        attestation: {
          report_id: reportId, definition_hash: verdict.definition_hash,
          verified_at: "2026-07-29T12:00:00Z",
        },
      }),
      serviceJobs(1),
    ]);
    expect(attest.isError).toBeFalsy();
    // Stage 10: the D-91.1 measure — nothing left but opening it.
    expect(attest.payload.pending_human_steps).toEqual([]);
    expect((attest.payload.created as { url: string }[])[0]!.url).toContain(`/reports/${reportId}`);

    // The permanent record and the audit trail (AT-9's assertion).
    const { rows: attestations } = await rig.core.pool.query(
      `SELECT report_id, definition_hash FROM report_attestations WHERE artifact_id = $1`,
      [art.id],
    );
    expect(attestations).toEqual([{ report_id: reportId, definition_hash: pbirHash }]);

    const calls = await auditRows(rig, { tool: "publish_report" });
    const mine = calls.filter(
      (row) => (row.result_meta as { artifact_id?: string }).artifact_id === art.id,
    );
    expect(mine.map((row) => (row.result_meta as { mode?: string }).mode)).toEqual([
      "deliver_model", "attest",
    ]);
    expect(mine.every((row) => row.decision === "allowed")).toBe(true);
  }, 120_000);
});

describe("AT-10 — session-side credential canary", () => {
  it("the compiled reporter bundle carries the PBIR tooling and no DB credential material", async () => {
    const out = await mkdtemp(path.join(tmpdir(), "at10-"));
    const setup = await compileProfile(
      "reporter",
      {
        name: "Reporter",
        roles: ["reporter"],
        skills: ["report"],
        tools: { allow: ["search_context", "validate_sql", "execute_sql:drill", "publish_report:powerbi"] },
        context: "Fixture reporter fragment.",
      },
      { publicUrl: "https://core.fixture.invalid" },
    );
    const written = await writeSetup(setup, out);

    // RA-5 made real: the tooling rides the bundle.
    expect(written).toContain(".claude/skills/report/pbir_tool.py");

    // The canary sweep: no DSN-shaped or secret-shaped material in any
    // compiled file. The session may hold a Power BI token by design
    // (RA-10); it must never hold a database credential (RA-2/AT-10).
    const forbidden = [
      /postgres(ql)?:\/\/[^\s"']+:[^\s"']+@/i, // DSN with embedded password
      /POWERBI_CLIENT_SECRET\s*=\s*[^\s{]/i,   // a secret VALUE (not a var name)
      /password\s*=\s*[^\s{)]/i,
      /BEGIN [A-Z ]*PRIVATE KEY/,
    ];
    for (const rel of written) {
      const content = await readFile(path.join(out, rel), "utf-8");
      for (const pattern of forbidden) {
        expect(content, `${rel} matches ${pattern}`).not.toMatch(pattern);
      }
    }
  });
});
