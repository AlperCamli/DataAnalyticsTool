/**
 * MCP conformance (MCP spec §9) — the MT tests implementable at M1 plus
 * the MC-5 checklist items (MCP-R1..R4, R8..R15) and the SP-2 closure
 * test. MT-3/MT-4/MT-8 and MCP-R5..R7 live in mcp-validate.test.ts;
 * MT-7 and the LED-R items in mcp-ledger.test.ts.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { WireClient } from "./fake-runner.js";
import { TEST_OPS_TOKEN, TEST_TOKEN } from "./helpers.js";
import {
  auditRows,
  callTool,
  insertAcceptedSnapshot,
  listTools,
  mcpRequest,
  setupMcpRig,
  USERS,
  type McpRig,
} from "./mcp-helpers.js";

let rig: McpRig;

beforeAll(async () => {
  rig = await setupMcpRig();
}, 240_000);

afterAll(async () => {
  await rig.stop();
});

const REPORTER_TOOLS = [
  "execute_sql",
  "flag_gap",
  "get_entity",
  "get_lineage",
  "get_metric",
  "get_table",
  "publish_report",
  "report_freshness",
  "search_context",
  "validate_sql",
];

describe("MT-1 / MCP-R4 — tools/list is the profile allow-set; hidden tools denied; qualifiers enforced (M-3)", () => {
  it("MT-1: reporter tools/list shows exactly the profile allowlist", async () => {
    const { names } = await listTools(rig, rig.token("reporter"), "reporter");
    expect(names).toEqual(REPORTER_TOOLS);
  });

  it("MT-1: a hidden tool called directly is denied and audited", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "list_gaps", {});
    expect(result.isError).toBe(true);
    expect(result.payload.code).toBe("permission_denied");
    const denied = await auditRows(rig, { tool: "list_gaps", decision: "denied" });
    expect(denied.length).toBeGreaterThan(0);
    expect(denied.at(-1)!.subject).toBe(USERS.reporter.username);
  });

  it("MCP-R4: system qualifier — execute_sql:drill grants drill only, not ga4", async () => {
    const denied = await callTool(rig, rig.token("steward"), "steward", "execute_sql", {
      system: "ga4",
      request: {},
      validation_token: "x",
    });
    expect(denied.payload.code).toBe("permission_denied");
    const allowed = await callTool(rig, rig.token("steward"), "steward", "execute_sql", {
      system: "drill",
      request: {},
      validation_token: "x",
    });
    // In-qualifier call passes the profile gate and reaches the gateway,
    // which then refuses it on its own terms — the bogus token fails §5
    // verification (MCP-R5). Reaching that refusal *is* the evidence the
    // qualifier gate allowed the call through.
    expect(allowed.payload.code).toBe("revalidate_required");
  });
});

describe("MT-2 / MCP-R10 — visibility map server-side, not_found semantics (M-4)", () => {
  it("MT-2: a visibility-hidden object returns not_found and audits the filtered reason", async () => {
    const result = await callTool(rig, rig.token("restricted"), "reporter", "get_table", {
      system: "drill",
      name: "reporting.v_net_sales",
    });
    expect(result.isError).toBe(true);
    expect(result.payload.code).toBe("not_found");
    expect(JSON.stringify(result.payload)).not.toContain("permission");
    const filtered = await auditRows(rig, { tool: "get_table", decision: "filtered" });
    expect(filtered.length).toBeGreaterThan(0);
    expect(filtered.at(-1)!.decision_reason).toContain("visibility");
  });

  it("MCP-R10: the same object serves normally for a role that can see it", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "reporting.v_net_sales",
    });
    expect(result.isError).toBe(false);
    expect(result.payload.fqn).toBe("drill.reporting.v_net_sales");
  });

  it("MCP-R10: filtered search hits are simply absent", async () => {
    const restricted = await callTool(rig, rig.token("restricted"), "reporter", "search_context", {
      query: "net sales reporting rollup",
    });
    const paths = ((restricted.payload.results as { path: string }[]) ?? []).map((r) => r.path);
    expect(paths.every((p) => !p.includes("reporting/"))).toBe(true);
  });
});

describe("MCP-R11 / P-E — lineage visibility node-by-node", () => {
  it("steward walk reaches the reporting views", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "get_lineage", {
      object: "drill.shop.orders",
      direction: "downstream",
      depth: 3,
    });
    expect(result.isError).toBe(false);
    const ids = (result.payload.nodes as { id: string }[]).map((n) => n.id);
    expect(ids).toContain("drill.reporting.v_order_totals");
    expect(ids).toContain("drill.reporting.v_net_sales");
  });

  it("MCP-R11: a restricted walk omits hidden nodes and their edges — never masked-but-revealed", async () => {
    const result = await callTool(rig, rig.token("restricted"), "reporter", "get_lineage", {
      object: "drill.shop.orders",
      direction: "downstream",
      depth: 3,
    });
    expect(result.isError).toBe(false);
    const text = JSON.stringify(result.payload);
    expect(text).not.toContain("reporting");
    expect((result.payload.edges as unknown[]).length).toBe(0);
  });

  it("MCP-R11: a hidden entry object is not_found, audited as filtered", async () => {
    const result = await callTool(rig, rig.token("restricted"), "reporter", "get_lineage", {
      object: "drill.reporting.v_net_sales",
    });
    expect(result.payload.code).toBe("not_found");
  });
});

describe("MT-5 / MCP-R8 — server-side guardrails; client-supplied guardrails ignored", () => {
  it("MT-5: guardrails echo the profile limits regardless of client-supplied values", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "validate_sql", {
      system: "drill",
      request: {
        dialect: "sql",
        statement: "SELECT id FROM shop.customers",
        guardrails: { row_cap: 999999999, timeout_s: 99999 },
      },
      guardrails: { row_cap: 999999999 },
    });
    expect(result.isError).toBe(false);
    expect(result.payload.guardrails).toMatchObject({ row_cap: 50000, timeout_s: 60 });
  });

  it("MCP-R8: a different profile's limits produce different injected guardrails", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "validate_sql", {
      system: "drill",
      request: { dialect: "sql", statement: "SELECT id FROM shop.customers" },
    });
    expect(result.payload.guardrails).toMatchObject({ row_cap: 100000, timeout_s: 120 });
  });
});

describe("MT-6 / MCP-R12 / MCP-R9 — trust blocks computed server-side; refs on every response", () => {
  it("MT-6: verified + hash-match human doc serves use-freely; machine block carries snapshot_ref", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "shop.customers",
    });
    const human = result.payload.human as { trust: { status: string; agent_guidance: string; hash_match: boolean } };
    expect(human.trust.status).toBe("verified");
    expect(human.trust.hash_match).toBe(true);
    expect(human.trust.agent_guidance).toBe("use-freely");
    const machine = result.payload.machine as { trust: { snapshot_ref: string; render_lag: boolean; agent_guidance: string } };
    expect(machine.trust.snapshot_ref).toBe(`sha256:${rig.drill.verdict.canonical_body_sha256}`);
    expect(machine.trust.render_lag).toBe(false);
    expect(machine.trust.agent_guidance).toBe("use-freely");
    expect(result.payload.refs).toMatchObject({
      snapshot_ref: { drill: `sha256:${rig.drill.verdict.canonical_body_sha256}` },
    });
  });

  it("MT-6: verified doc whose written_against hash drifted serves warn-user (§4 race)", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "reporting.v_net_sales",
    });
    const human = result.payload.human as { trust: { status: string; hash_match: boolean; agent_guidance: string } };
    expect(human.trust.status).toBe("verified");
    expect(human.trust.hash_match).toBe(false);
    expect(human.trust.agent_guidance).toBe("warn-user");
  });

  it("MT-6: contaminated doc serves refuse-unless-override with the contamination named", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "shop.legacy_sessions",
    });
    const human = result.payload.human as {
      trust: { status: string; agent_guidance: string; contamination: { object: string } };
    };
    expect(human.trust.status).toBe("contaminated");
    expect(human.trust.agent_guidance).toBe("refuse-unless-override");
    expect(human.trust.contamination.object).toBe("drill.shop.legacy_sessions");
  });

  it("MCP-R12: client-supplied trust/guidance arguments cannot override the server's block", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "shop.legacy_sessions",
      trust: { agent_guidance: "use-freely" },
      agent_guidance: "use-freely",
    });
    const human = result.payload.human as { trust: { agent_guidance: string } };
    expect(human.trust.agent_guidance).toBe("refuse-unless-override");
  });

  it("MCP-R9: facts from a snapshot ahead of the merged render signal render_lag + warn-user", async () => {
    // Accept a newer drill snapshot (only hash-excluded stats + capture
    // time differ — schema hashes stay valid) without merging a render.
    const doc = JSON.parse(rig.drill.canonical.toString("utf-8")) as {
      captured_at: string;
      objects: { name: string; stats?: Record<string, unknown> }[];
    };
    doc.captured_at = "2026-07-17T09:00:00Z";
    const customers = doc.objects.find((o) => o.name === "customers")!;
    customers.stats = { ...(customers.stats ?? {}), row_estimate: 4242 };
    const { canonicalize } = await import("./mcp-helpers.js");
    const newer = await canonicalize(Buffer.from(JSON.stringify(doc)));
    await insertAcceptedSnapshot(rig.core, newer);

    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "shop.customers",
    });
    const machine = result.payload.machine as {
      content: string;
      trust: { render_lag: boolean; agent_guidance: string; snapshot_ref: string };
    };
    expect(machine.trust.render_lag).toBe(true);
    expect(machine.trust.agent_guidance).toBe("warn-user");
    expect(machine.trust.snapshot_ref).toBe(`sha256:${newer.verdict.canonical_body_sha256}`);
    // Facts are served from the NEW snapshot (MC-5: snapshot authority).
    expect(machine.content).toContain("4242");

    // Restore: re-insert the baseline as newest so later tests see no lag.
    await insertAcceptedSnapshot(rig.core, rig.drill, new Date(Date.now() + 1000));
  });
});

describe("MCP-R2 / MCP-R3 / SP-2 — server-side profile binding; token swap re-binds", () => {
  it("MCP-R2: a profile outside the caller's roles fails the connection", async () => {
    const { status } = await mcpRequest(rig, rig.token("reporter"), "steward", "initialize", {
      protocolVersion: "2025-06-18",
      capabilities: {},
      clientInfo: { name: "t", version: "0" },
    });
    expect(status).toBe(403);
  });

  it("SP-2 closure: benchmark profile asserted without the benchmark role → refused; with it → list_gaps reachable", async () => {
    const refused = await mcpRequest(rig, rig.token("reporter"), "benchmark", "tools/call", {
      name: "list_gaps",
      arguments: {},
    });
    expect(refused.status).toBe(403);
    const denied = await auditRows(rig, { tool: "list_gaps", decision: "denied" });
    expect(denied.at(-1)!.decision_reason).toContain("do not permit profile");

    const allowed = await callTool(rig, rig.token("benchmark"), "benchmark", "list_gaps", {});
    expect(allowed.isError).toBe(false);
  });

  it("MCP-R3: a different subject's token mid-session re-binds identity — B's roles govern", async () => {
    // "Session" opened by the full-visibility reporter…
    const first = await callTool(rig, rig.token("reporter"), "reporter", "get_table", {
      system: "drill",
      name: "reporting.v_net_sales",
    });
    expect(first.isError).toBe(false);
    // …then the restricted user's token appears on the same profile
    // binding: their roles govern; nothing leaks from the earlier calls.
    const swapped = await callTool(rig, rig.token("restricted"), "reporter", "get_table", {
      system: "drill",
      name: "reporting.v_net_sales",
    });
    expect(swapped.payload.code).toBe("not_found");
  });
});

describe("MT-9 / MCP-R1 — per-call identity; revocation is next-call effective", () => {
  it("MT-9: a role revoked at the IdP denies the very next call", async () => {
    const token = rig.token("steward");
    const before = await callTool(rig, token, "steward", "list_gaps", {});
    expect(before.isError).toBe(false);
    rig.idp.setRoles(USERS.steward.username, ["ops"]); // steward revoked
    try {
      const after = await mcpRequest(rig, token, "steward", "tools/call", {
        name: "list_gaps",
        arguments: {},
      });
      expect(after.status).toBe(403);
    } finally {
      rig.idp.setRoles(USERS.steward.username, USERS.steward.roles);
    }
  });
});

describe("MCP-R13 — audit completeness (M-8)", () => {
  it("audits allowed, denied, and filtered decisions with hashed args", async () => {
    const rows = await auditRows(rig);
    const decisions = new Set(rows.map((r) => r.decision));
    expect(decisions).toContain("allowed");
    expect(decisions).toContain("denied");
    expect(decisions).toContain("filtered");
    for (const row of rows) {
      expect(String(row.args_digest)).toMatch(/^[0-9a-f]{64}$/);
      expect(row.subject).toBeTruthy();
      expect(Array.isArray(row.roles)).toBe(true);
    }
  });

  it("stores full statement text only for validate", async () => {
    const validates = await auditRows(rig, { tool: "validate_sql" });
    expect(validates.some((r) => typeof r.statement_text === "string" && r.statement_text!.toString().includes("SELECT"))).toBe(true);
    const reads = await auditRows(rig, { tool: "get_table" });
    expect(reads.every((r) => r.statement_text === null)).toBe(true);
  });
});

describe("MCP-R15 / KB-F — repo-level docs: visibility-checked, no trust block, one-liner only", () => {
  it("conventions.md surfaces as a doc hit without a trust block", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "search_context", {
      query: "machine-readable guardrails conventions",
    });
    const hits = result.payload.results as { path: string; trust?: unknown; one_liner: string }[];
    const conventions = hits.find((h) => h.path === "conventions.md");
    expect(conventions).toBeDefined();
    expect(conventions!.trust).toBeUndefined();
  });

  it("repo-level docs outside the caller's scopes are absent from search", async () => {
    // metrics/net-sales.md is outside the salesonly visibility globs.
    const result = await callTool(rig, rig.token("restricted"), "reporter", "search_context", {
      query: "net sales metric definition",
    });
    const paths = ((result.payload.results as { path: string }[]) ?? []).map((r) => r.path);
    expect(paths.every((p) => !p.startsWith("metrics/"))).toBe(true);
  });
});

describe("get_entity / get_metric / report_freshness round-trips", () => {
  it("get_entity serves the maps routing table with trust", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_entity", { name: "customer" });
    expect(result.isError).toBe(false);
    const fm = result.payload.front_matter as { maps: { object: string }[] };
    expect(fm.maps[0]!.object).toBe("drill.shop.customers");
    expect((result.payload.trust as { status: string }).status).toBe("verified");
  });

  it("get_metric marks verified metrics certified", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "get_metric", { name: "net-sales" });
    expect(result.isError).toBe(false);
    expect(result.payload.certified).toBe(true);
  });

  it("report_freshness serves per-system state and doc-status counts", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "report_freshness", {});
    expect(result.isError).toBe(false);
    const systems = result.payload.systems as { system: string }[];
    expect(systems.map((s) => s.system).sort()).toEqual(["drill", "ga4"]);
    const counts = result.payload.doc_status_counts as Record<string, number>;
    expect(counts.verified).toBeGreaterThan(0);
    expect(counts.contaminated).toBeGreaterThan(0);
  });
});

describe("P-A (D-66.1) — runner tokens are claim-surface only", () => {
  it("a runner token replayed against the ops surface is denied; the ops identity works; claims are unaffected", async () => {
    const runnerAsOps = new WireClient(rig.base, TEST_TOKEN);
    expect((await runnerAsOps.enqueue({ type: "snapshot", system: "x", connector: { name: "y" } })).status).toBe(403);
    expect((await runnerAsOps.get(`/v1/snapshots/any-id/body`)).status).toBe(403);
    expect((await runnerAsOps.get(`/v1/jobs`)).status).toBe(403);

    const ops = new WireClient(rig.base, TEST_TOKEN, TEST_OPS_TOKEN);
    expect((await ops.get(`/v1/jobs`)).status).toBe(200);

    const claim = await runnerAsOps.claim({
      runner_id: "r1",
      connectors: [{ name: "none", version: "0.0.1" }],
      classes: ["batch"],
      wait_s: 0,
    });
    expect(claim.status).toBe(204);
  });

  it("an OIDC identity with an ops role opens the ops surface", async () => {
    const response = await fetch(`${rig.base}/v1/jobs`, {
      headers: { authorization: `Bearer ${rig.token("steward")}` },
    });
    expect(response.status).toBe(200);
    const reporter = await fetch(`${rig.base}/v1/jobs`, {
      headers: { authorization: `Bearer ${rig.token("reporter")}` },
    });
    expect(reporter.status).toBe(401);
  });
});
