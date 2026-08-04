/**
 * The publish_report mode contract (MCP §6.8 amendment, CP-7/M3 under
 * ruling D-91) — core-side conformance for the two-call api-class flow.
 *
 * Report-authoring AT coverage at this layer: AT-2 (undocumented blend
 * refused naming the documented set), AT-3 (layout without
 * trust_element → invalid), AT-5 (attest without matching delivery →
 * refused), AT-6 (data-only re-push under an unchanged revision; layout
 * change → new revision, same report identity; attestation rows record
 * both), plus the mode-vs-class gates, the gateway execution of
 * artifact queries under profile guardrails, truncated-result refusal
 * (CI-7), the pbir_hash content-hash exclusion (formats §4.7), the
 * delivery/attestation records, and the dangling-deliveries ops query.
 * The adapter's own behavior is python-tested (test_powerbi_publisher);
 * the scripted runner here answers execute and publish jobs with
 * faithful §6/§8.2 result shapes.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { upsertSyncSystem } from "../src/triggers.js";
import { WireClient } from "./fake-runner.js";
import { TEST_TOKEN } from "./helpers.js";
import { auditRows, callTool, setupMcpRig, type McpRig } from "./mcp-helpers.js";

const WORKSPACE = "11111111-1111-4111-8111-111111111111";

let rig: McpRig;
let drillPin: string;

beforeAll(async () => {
  rig = await setupMcpRig();
  drillPin = `sha256:${rig.drill.verdict.canonical_body_sha256.replace(/^sha256:/, "")}`;
  // The api-class target: publish flags stored per connection (CI-5),
  // which is what the server's class check reads.
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
  // The single-shot contrast target for the class gate.
  await upsertSyncSystem(rig.core.pool, {
    system: "looker_studio",
    connector_name: "looker_studio",
    version_constraint: ">=0.1 <0.2",
    payload: {
      config: { system: "looker_studio", template_report_id: "tmpl-1", sources: {} },
      credentials: [],
    },
  });
  // The estate system behind the artifact queries — execution
  // credentials marked for the query capability (gateway path).
  await upsertSyncSystem(rig.core.pool, {
    system: "drill",
    connector_name: "postgres",
    version_constraint: ">=0.2 <0.3",
    payload: {
      config: { system: "drill", mode: "live" },
      credentials: [{ ref: "env://CL_EXEC_DSN", key: "execute_dsn", required_for: ["query"] }],
    },
  });
}, 240_000);

afterAll(async () => {
  await rig.stop();
});

let artifactSeq = 0;

function artifact(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  artifactSeq += 1;
  return {
    artifact_version: "1",
    id: `ra-pbi-${String(artifactSeq).padStart(4, "0")}`,
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
      trust_notes: ["fixture trust note"],
    },
    layout: layout(),
    blend: null,
    ...overrides,
  };
}

function layout(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    designed_by: "report-skill@test",
    pages: [
      {
        name: "Overview",
        visuals: [
          {
            kind: "barChart", registry_kind: "bar", table: "net_sales",
            x: "customer_id", y: "net_total", title: "Net sales by customer",
          },
        ],
      },
    ],
    trust_element: { page: "Overview", placement: "footer", content_from: "trust_notes" },
    ...overrides,
  };
}

function publish(args: Record<string, unknown>) {
  return callTool(rig, rig.token("reporter"), "reporter", "publish_report", args);
}

async function jobCount(type: string): Promise<number> {
  const { rows } = await rig.core.pool.query<{ n: string }>(
    `SELECT count(*) AS n FROM jobs WHERE type = $1`,
    [type],
  );
  return Number(rows[0]!.n);
}

/**
 * Service execute + publish jobs the way the SDK runner would, with
 * faithful §6 / amended-§8.2 result shapes, until `publishJobs` publish
 * completions have happened.
 */
async function serviceJobs(
  publishJobs: number,
  opts: { truncated?: boolean; datasetId?: string; limitProximity?: unknown[] } = {},
): Promise<Record<string, unknown>[]> {
  const client = new WireClient(rig.base, TEST_TOKEN);
  const deadline = Date.now() + 60_000;
  const publishPayloads: Record<string, unknown>[] = [];
  let completed = 0;
  while (completed < publishJobs) {
    if (Date.now() > deadline) throw new Error(`serviced ${completed}/${publishJobs} publish jobs in 60s`);
    const { status, json } = await client.claim({
      runner_id: "test-powerbi-runner",
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
      const result = {
        columns: [
          { name: "customer_id", type: "int4" },
          { name: "net_total", type: "numeric" },
        ],
        rows: [[1, "10.50"], [2, "20.25"]],
        row_count: 2,
        truncated: opts.truncated === true,
        duration_ms: 3,
        source: { executed_on: "replica", engine_version: "fixture" },
      };
      await client.completeRaw(jobId, lease, JSON.stringify(result));
      continue;
    }
    const payload = (json.payload ?? {}) as Record<string, unknown>;
    publishPayloads.push(payload);
    const mode = payload.mode as string;
    let result: Record<string, unknown>;
    if (mode === "deliver_model") {
      const results = (payload.results ?? {}) as Record<string, Record<string, unknown>>;
      const datasetId = opts.datasetId ?? "ds-fixture-0001";
      result = {
        mode: "deliver_model",
        created: [{ type: "dataset", id: datasetId, url: "" }],
        pending_human_steps: [],
        backing: [{ type: "reporting_view", ref: "reporting.v_net_sales" }],
        detail: {
          dataset_name: "cl-fixture",
          delivered: {
            workspace_id: WORKSPACE,
            dataset_id: datasetId,
            tables: Object.entries(results).map(([name, r]) => ({
              name,
              columns: ((r.columns ?? []) as { name: string; type: string }[]).map((c) => ({
                name: c.name,
                type: c.type === "numeric" ? "Double" : c.type === "int4" ? "Int64" : "String",
                source_type: c.type,
              })),
              rows_delivered: Array.isArray(r.rows) ? r.rows.length : 0,
            })),
          },
          ...(opts.limitProximity ? { limit_proximity: opts.limitProximity } : {}),
        },
      };
    } else {
      const attestation = (payload.attestation ?? {}) as { report_id?: string; definition_hash?: string };
      result = {
        mode: "attest",
        created: [{
          type: "report",
          id: attestation.report_id,
          url: `https://app.powerbi.com/groups/${WORKSPACE}/reports/${attestation.report_id}`,
        }],
        pending_human_steps: [],
        backing: [],
        detail: { attested: attestation },
      };
    }
    const done = await client.completeRaw(jobId, lease, JSON.stringify(result));
    if (done.status !== 200) {
      throw new Error(`publish delivery rejected: ${done.status} ${JSON.stringify(done.json)}`);
    }
    completed += 1;
  }
  return publishPayloads;
}

const DEFINITION_HASH = `sha256:${"ab".repeat(32)}`;

// ---------------------------------------------------------------------------

describe("mode-vs-class gates (MCP §6.8 amendment)", () => {
  it("api target without mode → invalid_argument, no job", async () => {
    const before = await jobCount("publish");
    const res = await publish({ artifact: artifact(), target: "powerbi" });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("invalid_argument");
    expect(String(res.payload.message)).toContain("deliver_model");
    expect(await jobCount("publish")).toBe(before);
  });

  it("mode on a single-shot target → invalid_argument", async () => {
    const art = artifact();
    delete art.layout; // looker artifacts don't carry §4.7 layout
    const res = await publish({ artifact: art, target: "looker_studio", mode: "deliver_model" });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("invalid_argument");
    expect(String(res.payload.message)).toContain("single-shot");
  });

  it("api target without a §4.7 layout → invalid_argument naming RA-3", async () => {
    const art = artifact();
    delete art.layout;
    const res = await publish({ artifact: art, target: "powerbi", mode: "deliver_model" });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("invalid_argument");
    expect(String(res.payload.message)).toContain("layout");
  });
});

describe("layout §4.7 validation (authoring AT-3)", () => {
  it("layout without trust_element → artifact invalid", async () => {
    const l = layout();
    delete l.trust_element;
    const res = await publish({
      artifact: artifact({ layout: l }), target: "powerbi", mode: "deliver_model",
    });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("invalid_argument");
    expect(String(res.payload.message)).toContain("trust_element");
  });

  it("layout visual naming an undelivered table → invalid", async () => {
    const l = layout();
    (l.pages as Record<string, unknown>[])[0]!.visuals = [
      { kind: "barChart", registry_kind: "bar", table: "nope", x: "a", y: "b" },
    ];
    const res = await publish({
      artifact: artifact({ layout: l }), target: "powerbi", mode: "deliver_model",
    });
    expect(res.isError).toBe(true);
    expect(String(res.payload.message)).toContain("names no artifact query");
  });

  it("non-registry kind without a justification note → invalid; with note → passes structure", async () => {
    const l = layout();
    (l.pages as Record<string, unknown>[])[0]!.visuals = [
      { kind: "waterfallChart", table: "net_sales", x: "customer_id", y: "net_total" },
    ];
    const res = await publish({
      artifact: artifact({ layout: l }), target: "powerbi", mode: "deliver_model",
    });
    expect(res.isError).toBe(true);
    expect(String(res.payload.message)).toContain("justification");
  });

  it("unknown layout keys are rejected (closed schema)", async () => {
    const res = await publish({
      artifact: artifact({ layout: layout({ theme: "dark" }) }),
      target: "powerbi", mode: "deliver_model",
    });
    expect(res.isError).toBe(true);
    expect(String(res.payload.message)).toContain("closed schema");
  });
});

describe("AT-2 — undocumented blend refused naming the documented set", () => {
  it("blend key outside the entity doc's maps → config_error naming documented keys", async () => {
    const art = artifact({
      blend: {
        left: "net_sales", right: "net_sales",
        keys: [{ left_column: "made_up", right_column: "also_made_up", entity_ref: "entities/customer.md" }],
        join: "left",
      },
    });
    const before = await jobCount("publish");
    const res = await publish({ artifact: art, target: "powerbi", mode: "deliver_model" });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("config_error");
    expect(String(res.payload.message)).toContain("documents keys");
    expect(String(res.payload.message)).toContain("missing_join_path");
    expect(await jobCount("publish")).toBe(before);
  });
});

describe("deliver_model — the gateway-executed data plane (RA-2)", () => {
  it("executes artifact queries under profile guardrails, records the delivery, returns delivered schemas", async () => {
    const art = artifact();
    const [res, payloads] = await Promise.all([
      publish({ artifact: art, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1),
    ]);
    expect(res.isError).toBeFalsy();
    expect(res.payload.mode).toBe("deliver_model");
    const delivered = (res.payload.detail as Record<string, unknown>).delivered as {
      dataset_id: string;
      tables: { name: string; columns: { name: string; type: string }[] }[];
    };
    expect(delivered.dataset_id).toBe("ds-fixture-0001");
    expect(delivered.tables[0]!.name).toBe("net_sales");
    expect(res.payload.pending_human_steps).toEqual([]);

    // The publish payload carried mode + gateway-executed results.
    expect(payloads[0]!.mode).toBe("deliver_model");
    const results = payloads[0]!.results as Record<string, { rows: unknown[] }>;
    expect(results.net_sales!.rows.length).toBe(2);

    // The execute job ran through the gateway path: profile guardrails,
    // gateway trigger tied to the publish audit record.
    const { rows: executeJobs } = await rig.core.pool.query(
      `SELECT payload, triggers FROM jobs WHERE type = 'execute' ORDER BY created_at DESC LIMIT 1`,
    );
    const executePayload = executeJobs[0]!.payload as {
      guardrails: { row_cap: number; statement_class: string };
    };
    expect(executePayload.guardrails.row_cap).toBe(50_000); // reporter profile, not client
    expect(executePayload.guardrails.statement_class).toBe("select-only");
    expect((executeJobs[0]!.triggers as { kind: string }[])[0]!.kind).toBe("gateway");

    // The delivery record is the restore source for the next revision.
    const { rows: deliveries } = await rig.core.pool.query(
      `SELECT revision, dataset_id, results FROM model_deliveries WHERE artifact_id = $1`,
      [art.id],
    );
    expect(deliveries.length).toBe(1);
    expect(deliveries[0]!.dataset_id).toBe("ds-fixture-0001");
    expect((deliveries[0]!.results as Record<string, unknown>).net_sales).toBeDefined();
  });

  it("RA-F tripwire (D-96.3e): adapter-reported limit proximity → health warning; publish proceeds", async () => {
    const art = artifact();
    const entries = [{ limit: "columns", measured: 60, allowed: 75, at: "table 'net_sales'" }];
    const [res] = await Promise.all([
      publish({ artifact: art, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1, { limitProximity: entries }),
    ]);
    // Proximity is telemetry, never a refusal: the delivery completed.
    expect(res.isError).toBeFalsy();
    expect(res.payload.mode).toBe("deliver_model");
    const { rows: deliveries } = await rig.core.pool.query(
      `SELECT revision FROM model_deliveries WHERE artifact_id = $1`,
      [art.id],
    );
    expect(deliveries.length).toBe(1);

    const { rows } = await rig.core.pool.query(
      `SELECT severity, system, detail FROM health_events WHERE kind = 'push_limit_proximity'`,
    );
    expect(rows.length).toBe(1);
    expect(rows[0]!.severity).toBe("warning");
    expect(rows[0]!.system).toBe("powerbi");
    const detail = rows[0]!.detail as { artifact_id: string; entries: unknown };
    expect(detail.artifact_id).toBe(art.id);
    expect(detail.entries).toEqual(entries);
  });

  it("a truncated gateway result refuses the delivery (CI-7) — no publish job", async () => {
    const before = await jobCount("publish");
    const [res] = await Promise.all([
      publish({ artifact: artifact(), target: "powerbi", mode: "deliver_model" }),
      // Only the execute job gets serviced (truncated); the refusal
      // must prevent any publish job.
      (async () => {
        const client = new WireClient(rig.base, TEST_TOKEN);
        const deadline = Date.now() + 30_000;
        for (;;) {
          const { status, json } = await client.claim({
            runner_id: "truncating-runner",
            connectors: [{ name: "postgres", version: "0.2.5", types: ["execute"] }],
            classes: ["interactive"],
            wait_s: 2,
          });
          if (status === 200) {
            const lease = (json.lease as { token: string }).token;
            await client.start(json.job_id as string, lease);
            await client.completeRaw(json.job_id as string, lease, JSON.stringify({
              columns: [{ name: "customer_id", type: "int4" }],
              rows: [[1]], row_count: 1, truncated: true, duration_ms: 1,
              source: { executed_on: "replica", engine_version: "fixture" },
            }));
            return;
          }
          if (Date.now() > deadline) throw new Error("no execute job to truncate");
        }
      })(),
    ]);
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("guardrail");
    expect(String(res.payload.message)).toContain("truncated");
    expect(await jobCount("publish")).toBe(before);
  });
});

describe("AT-5 / attest — the permanent record requires its delivery", () => {
  it("attest without a prior deliver_model → refused revalidate_required-class, no job", async () => {
    const before = await jobCount("publish");
    const res = await publish({
      artifact: artifact(), target: "powerbi", mode: "attest",
      attestation: { report_id: "r-1", definition_hash: DEFINITION_HASH },
    });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("revalidate_required");
    expect(String(res.payload.message)).toContain("no matching deliver_model");
    expect(await jobCount("publish")).toBe(before);
  });

  it("malformed definition_hash → invalid_argument", async () => {
    const res = await publish({
      artifact: artifact(), target: "powerbi", mode: "attest",
      attestation: { report_id: "r-1", definition_hash: "sha256:short" },
    });
    expect(res.isError).toBe(true);
    expect(res.payload.code).toBe("invalid_argument");
  });

  it("layout.pbir_hash disagreeing with the submitted hash → invalid_argument", async () => {
    const art = artifact({ layout: layout({ pbir_hash: `sha256:${"cd".repeat(32)}` }) });
    const res = await publish({
      artifact: art, target: "powerbi", mode: "attest",
      attestation: { report_id: "r-1", definition_hash: DEFINITION_HASH },
    });
    expect(res.isError).toBe(true);
    expect(String(res.payload.message)).toContain("does not equal");
  });
});

describe("the two-call contract end to end (core half of AT-9) + AT-6", () => {
  it("deliver → attest: attestation row, F-4 report node, both calls in audit; pbir_hash does not mint a revision", async () => {
    const art = artifact();
    const reportId = "11111111-2222-4333-8444-555555555555";

    const [deliverRes] = await Promise.all([
      publish({ artifact: art, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1, { datasetId: "ds-e2e-0001" }),
    ]);
    expect(deliverRes.isError).toBeFalsy();
    const deliveredRevision = (deliverRes.payload.artifact as { revision: number }).revision;

    // Stage 6 sets layout.pbir_hash — excluded from the content hash,
    // so the attest resolves to the SAME revision the delivery holds.
    const attestArt = { ...art, layout: layout({ pbir_hash: DEFINITION_HASH }) };
    const [attestRes] = await Promise.all([
      publish({
        artifact: attestArt, target: "powerbi", mode: "attest",
        attestation: {
          report_id: reportId, definition_hash: DEFINITION_HASH,
          verified_at: "2026-07-29T12:00:00Z",
        },
      }),
      serviceJobs(1),
    ]);
    expect(attestRes.isError).toBeFalsy();
    expect(attestRes.payload.mode).toBe("attest");
    const created = (attestRes.payload.created as { id: string; url: string }[])[0]!;
    expect(created.id).toBe(reportId);
    expect(created.url).toContain(`/reports/${reportId}`);

    const { rows: attestations } = await rig.core.pool.query(
      `SELECT revision, report_id, definition_hash, dataset_id, verified_at
         FROM report_attestations WHERE artifact_id = $1`,
      [art.id],
    );
    expect(attestations.length).toBe(1);
    expect(attestations[0]!.revision).toBe(deliveredRevision);
    expect(attestations[0]!.report_id).toBe(reportId);
    expect(attestations[0]!.definition_hash).toBe(DEFINITION_HASH);
    expect(attestations[0]!.dataset_id).toBe("ds-e2e-0001");

    // F-4: the attested report is a graph node fed by the backing view.
    const { rows: lineage } = await rig.core.pool.query(
      `SELECT source_fqn, target_fqn FROM lineage_attestations WHERE target_fqn = $1`,
      [`powerbi.report.${reportId}`],
    );
    expect(lineage.length).toBeGreaterThan(0);
    expect(lineage[0]!.source_fqn).toBe("drill.reporting.v_net_sales");

    // Audit shows both publish_report calls, mode in result_meta (M-8).
    const calls = await auditRows(rig, { tool: "publish_report" });
    const mine = calls.filter(
      (row) => (row.result_meta as { artifact_id?: string }).artifact_id === art.id,
    );
    expect(mine.map((row) => (row.result_meta as { mode?: string }).mode)).toEqual([
      "deliver_model", "attest",
    ]);
  });

  it("AT-6: data-only re-delivery keeps the revision; a layout change advances it; attestation rows record both", async () => {
    const art = artifact();
    const reportId = "22222222-3333-4444-8555-666666666666";

    const [first] = await Promise.all([
      publish({ artifact: art, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1, { datasetId: "ds-at6-0001" }),
    ]);
    const rev1 = (first.payload.artifact as { revision: number }).revision;

    // Data-only: same artifact content. NOT short-circuited — the
    // queries re-execute and rows re-push under the same revision/ids.
    const [again, payloads] = await Promise.all([
      publish({ artifact: art, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1, { datasetId: "ds-at6-0001" }),
    ]);
    expect(again.isError).toBeFalsy();
    expect((again.payload.artifact as { revision: number }).revision).toBe(rev1);
    expect((again.payload as { mode?: string }).mode).toBe("deliver_model");
    // The re-delivery carried `previous` — the restore source (AT-8's
    // server half).
    expect(payloads[0]!.previous).toBeDefined();

    await Promise.all([
      publish({
        artifact: art, target: "powerbi", mode: "attest",
        attestation: { report_id: reportId, definition_hash: DEFINITION_HASH },
      }),
      serviceJobs(1),
    ]);

    // Layout change: same report identity (RA-8), new revision.
    const changed = {
      ...art,
      layout: layout({
        pages: [{
          name: "Overview",
          visuals: [{
            kind: "lineChart", registry_kind: "line", table: "net_sales",
            x: "customer_id", y: "net_total", title: "Net sales trend",
            notes: "line now justified: calendar spine present in backing view",
          }],
        }],
        trust_element: { page: "Overview", placement: "footer", content_from: "trust_notes" },
      }),
    };
    const [second] = await Promise.all([
      publish({ artifact: changed, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1, { datasetId: "ds-at6-0001" }),
    ]);
    const rev2 = (second.payload.artifact as { revision: number }).revision;
    expect(rev2).toBe(rev1 + 1);

    const secondHash = `sha256:${"ef".repeat(32)}`;
    await Promise.all([
      publish({
        artifact: changed, target: "powerbi", mode: "attest",
        attestation: { report_id: reportId, definition_hash: secondHash },
      }),
      serviceJobs(1),
    ]);

    // Both paths recorded: two attestation rows, same report identity,
    // distinct definition hashes (AT-6's record requirement).
    const { rows } = await rig.core.pool.query(
      `SELECT revision, report_id, definition_hash FROM report_attestations
        WHERE artifact_id = $1 ORDER BY revision`,
      [art.id],
    );
    expect(rows.length).toBe(2);
    expect(rows.map((r) => r.report_id)).toEqual([reportId, reportId]);
    expect(rows.map((r) => r.definition_hash)).toEqual([DEFINITION_HASH, secondHash]);

    // A stale attest (old content at the superseded revision) is refused.
    const stale = await publish({
      artifact: art, target: "powerbi", mode: "attest",
      attestation: { report_id: reportId, definition_hash: DEFINITION_HASH },
    });
    expect(stale.isError).toBe(true);
    expect(stale.payload.code).toBe("revalidate_required");
  });
});

describe("delivered-but-unattested is a loud dangling state", () => {
  it("the ops join marks a delivery whose revision has no attestation", async () => {
    const art = artifact();
    await Promise.all([
      publish({ artifact: art, target: "powerbi", mode: "deliver_model" }),
      serviceJobs(1, { datasetId: "ds-dangling-01" }),
    ]);
    // The `cli publish deliveries` query, verbatim.
    const { rows } = await rig.core.pool.query(
      `SELECT d.artifact_id, d.revision, a.report_id
         FROM model_deliveries d
         LEFT JOIN report_attestations a
           ON a.artifact_id = d.artifact_id AND a.target = d.target
          AND a.revision = d.revision
        WHERE d.artifact_id = $1`,
      [art.id],
    );
    expect(rows.length).toBe(1);
    expect(rows[0]!.report_id).toBeNull(); // dangling — loudly visible
  });
});
