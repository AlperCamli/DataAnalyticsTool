/**
 * Rig for the CP-4 MCP conformance suites: an in-process dev IdP
 * (introspection-backed, mutable roles — the MT-9 lever), a scratch KB
 * built from the drill fixture (two schemas — `shop` visible to a
 * restricted role, `reporting` hidden — plus entity/metric/human docs
 * and a real lineage graph) with roles.yaml, three profiles, and a
 * conventions guardrail block; accepted snapshots (drill = SQL,
 * ga4 = API fixture) inserted as canonical bytes so the workspace,
 * trust hashes, and render-lag comparisons are the real thing.
 */

import { randomBytes } from "node:crypto";
import { execFileSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { startDevIdp, type DevIdp } from "../src/devidp.js";
import { parseFrontMatter } from "../src/kbread.js";
import { pythonPath, repoRoot, startCore, type TestCore } from "./helpers.js";
import { drillSnapshot, initScratchKb, py, syncConfig, type ScratchKb } from "./sync-helpers.js";

export const USERS = {
  steward: { username: "alper-steward", password: "pw", roles: ["steward", "ops"], display: "A. Steward" },
  reporter: { username: "rene-reporter", password: "pw", roles: ["reporter"], display: "R. Reporter" },
  restricted: { username: "sam-restricted", password: "pw", roles: ["salesonly"], display: "S. Restricted" },
  benchmark: { username: "bench-bot", password: "pw", roles: ["benchmark"], display: "Benchmark" },
  /** Steward-profile access with shop-only visibility — the LED-R2/FL-5
   * "issues attributed to objects the caller cannot see are omitted" case. */
  auditlite: { username: "aud-lite", password: "pw", roles: ["auditlite"], display: "Audit Lite" },
  /** Execute grant with a row_cap of 5 — the CI-7 truncation evidence. */
  capped: { username: "cap-user", password: "pw", roles: ["capped"], display: "Capped User" },
  /** CP-5 baseline `no-kb` condition (D-74.4): validate/execute, no content tools. */
  nokb: { username: "nokb-bot", password: "pw", roles: ["nokb"], display: "No-KB Benchmark" },
};

const ROLES_YAML = `# Scratch-KB role map (KB-A per-directory globs).
roles:
  R1:
    profile: reporter
    oidc_group: reporter
    visibility:
      - index.md
      - conventions.md
      - systems/**
      - entities/**
      - metrics/**
      - lineage/**
  R1b:
    profile: reporter
    oidc_group: salesonly
    visibility:
      - index.md
      - conventions.md
      - systems/drill/index.md
      - systems/drill/shop/**
      - entities/**
  R2:
    profile: steward
    oidc_group: steward
    visibility: ["**"]
  R2b:
    profile: steward
    oidc_group: auditlite
    visibility:
      - index.md
      - conventions.md
      - systems/drill/index.md
      - systems/drill/shop/**
  R6:
    profile: benchmark
    oidc_group: benchmark
    visibility: ["**"]
  R7:
    profile: capped
    oidc_group: capped
    visibility: ["**"]
`;

const REPORTER_PROFILE = `name: Reporter
description: Read + validate for business users
roles: [reporter, salesonly]
skills: [report]
tools:
  allow: [search_context, get_entity, get_table, get_metric, get_lineage,
          validate_sql, report_freshness, flag_gap]
limits: { row_cap: 50000, timeout_s: 60 }
`;

const STEWARD_PROFILE = `name: Steward
description: Full read surface + triage
roles: [steward, auditlite]
skills: [enrich, review-sync]
tools:
  allow: [search_context, get_entity, get_table, get_metric, get_lineage,
          validate_sql, execute_sql:drill, report_freshness, flag_gap, list_gaps]
limits: { row_cap: 100000, timeout_s: 120 }
`;

const BENCHMARK_PROFILE = `name: Benchmark
description: Golden-suite harness profile (SP-2 waiver keys on this, server-resolved)
roles: [benchmark]
skills: [benchmark]
tools:
  allow: [search_context, get_entity, get_table, get_metric, get_lineage,
          validate_sql, report_freshness, flag_gap, list_gaps]
limits: { row_cap: 50000, timeout_s: 60 }
`;

/**
 * The CP-5 baseline's `no-kb` condition (D-74.4a): validate + execute
 * across *every* system, and no content tools at all. The condition is
 * "discover the estate live" — `information_schema` for SQL, the GA4
 * metadata endpoint, GSC's fixed schema — so the grant spans all systems;
 * a supabase-only grant would score the GA4/GSC cases as failures of the
 * condition rather than of the KB.
 */
const NOKB_PROFILE = `name: No-KB
description: Baseline v1 no-kb condition — live discovery, no context tools
roles: [nokb]
skills: [report]
tools:
  allow: [validate_sql, execute_sql:drill, execute_sql:ga4, flag_gap]
limits: { row_cap: 50000, timeout_s: 60 }
`;

const CAPPED_PROFILE = `name: Capped
description: Execution with a deliberately tiny row cap (CI-7 truncation evidence)
roles: [capped]
skills: [report]
tools:
  allow: [search_context, get_entity, get_table, get_metric, get_lineage,
          validate_sql, execute_sql:drill, report_freshness, flag_gap]
limits: { row_cap: 5, timeout_s: 30 }
`;

const CONVENTIONS = `# Conventions (scratch)

## Machine-readable guardrails

\`\`\`yaml
drill:
  dialect: postgres
  statement_class: select-only
  timeout_s: 60
  row_cap: 50000
ga4:
  dialect: api
  operation: runReport
  row_cap: 50000
\`\`\`
`;

export interface CanonicalSnapshot {
  verdict: {
    valid: boolean;
    system: string;
    snapshot_version: string;
    source_mode: string;
    captured_at: string;
    connector: { name: string; version: string };
    object_count: number;
    sha256: string;
    canonical_body_sha256: string;
  };
  canonical: Buffer;
}

/** Run the real delivery-gate CLI over raw snapshot bytes. */
export async function canonicalize(bytes: Buffer): Promise<CanonicalSnapshot> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-canon-"));
  const file = path.join(dir, "doc.json");
  const out = path.join(dir, "canonical.json");
  await writeFile(file, bytes);
  const stdout = execFileSync(pythonPath(), ["-m", "snapshot.accept", file, "--out", out], {
    cwd: repoRoot(),
    encoding: "utf-8",
    env: { ...process.env, PYTHONPATH: repoRoot() },
  });
  const verdict = JSON.parse(stdout) as CanonicalSnapshot["verdict"];
  if (!verdict.valid) throw new Error(`fixture snapshot invalid: ${stdout}`);
  return { verdict, canonical: await readFile(out) };
}

export async function insertAcceptedSnapshot(
  core: TestCore,
  snap: CanonicalSnapshot,
  acceptedAt?: Date,
): Promise<string> {
  const id = `snap-${randomBytes(8).toString("hex")}`;
  await core.pool.query(
    `INSERT INTO accepted_snapshots
       (snapshot_id, system, job_id, snapshot_version, source_mode,
        connector_name, connector_version, captured_at, body, sha256,
        canonical_body_sha256, object_count, accepted_at)
     VALUES ($1,$2,NULL,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`,
    [
      id,
      snap.verdict.system,
      snap.verdict.snapshot_version,
      snap.verdict.source_mode,
      snap.verdict.connector.name,
      snap.verdict.connector.version,
      snap.verdict.captured_at,
      snap.canonical,
      snap.verdict.sha256,
      snap.verdict.canonical_body_sha256,
      snap.verdict.object_count,
      acceptedAt ?? new Date(),
    ],
  );
  return id;
}

export interface McpRig {
  core: TestCore;
  kb: ScratchKb;
  idp: DevIdp;
  drill: CanonicalSnapshot;
  ga4: CanonicalSnapshot;
  base: string;
  token: (user: keyof typeof USERS) => string;
  stop: () => Promise<void>;
}

export async function setupMcpRig(
  overrides: {
    limits?: Partial<TestCore["cfg"]["mcp"]["limits"]>;
    /**
     * Visibility map to seed. Omit for the standard suite map; pass
     * `null` to commit **no** `roles.yaml` at all — the CP-5 `no-kb`
     * condition's scratch repo, where the map's absence is what makes
     * the full surface visible (D-74.4b/4c).
     */
    rolesYaml?: string | null;
  } = {},
): Promise<McpRig> {
  const base = await mkdtemp(path.join(tmpdir(), "cl-mcp-"));
  const idp = await startDevIdp({ users: Object.values(USERS) });
  const kb = await initScratchKb(base);

  const drill = await canonicalize(await drillSnapshot("before"));
  const ga4 = await canonicalize(await readFile(path.join(repoRoot(), "fixtures", "ga4.json")));

  // Seed the scratch KB: drill kb-seed + CP-4 surface files.
  await cp(path.join(repoRoot(), "fixtures", "drill", "kb-seed"), kb.seedClone, { recursive: true });
  await writeFile(path.join(kb.seedClone, "index.md"), "# Scratch KB\n\nEntry point.\n");
  await writeFile(path.join(kb.seedClone, "conventions.md"), CONVENTIONS);
  await mkdir(path.join(kb.seedClone, ".contextlayer", "profiles"), { recursive: true });
  const rolesYaml = overrides.rolesYaml === undefined ? ROLES_YAML : overrides.rolesYaml;
  if (rolesYaml !== null) {
    await writeFile(path.join(kb.seedClone, ".contextlayer", "roles.yaml"), rolesYaml);
  }
  await writeFile(path.join(kb.seedClone, ".contextlayer", "profiles", "reporter.yaml"), REPORTER_PROFILE);
  await writeFile(path.join(kb.seedClone, ".contextlayer", "profiles", "steward.yaml"), STEWARD_PROFILE);
  await writeFile(path.join(kb.seedClone, ".contextlayer", "profiles", "benchmark.yaml"), BENCHMARK_PROFILE);
  await writeFile(path.join(kb.seedClone, ".contextlayer", "profiles", "capped.yaml"), CAPPED_PROFILE);
  await writeFile(path.join(kb.seedClone, ".contextlayer", "profiles", "nokb.yaml"), NOKB_PROFILE);

  // The contaminated fixture doc the M1 demo surfaces (KB §5 semantics).
  const legacyPath = path.join(kb.seedClone, "systems", "drill", "shop", "legacy_sessions.md");
  const legacy = await readFile(legacyPath, "utf-8");
  await writeFile(
    legacyPath,
    legacy
      .replace(/^status: .*$/m, "status: contaminated")
      .replace(
        /^contamination: null$/m,
        'contamination: { object: "drill.shop.legacy_sessions", change: "removed", detail: "fixture contamination" }',
      ),
  );

  // Pins are the canonical bytes (what sync commits), then render +
  // lineage exactly as task 1.6 does.
  const pinDir = path.join(kb.seedClone, ".contextlayer", "snapshots");
  await mkdir(pinDir, { recursive: true });
  const drillPin = path.join(pinDir, "drill.json");
  const ga4Pin = path.join(pinDir, "ga4.json");
  await writeFile(drillPin, drill.canonical);
  await writeFile(ga4Pin, ga4.canonical);
  py(["-m", "generator.render", drillPin, ga4Pin, "--out", kb.seedClone]);
  py(["-m", "lineage", drillPin, ga4Pin, "--kb", kb.seedClone]);

  // Repair customers.md written_against to the real rendered hash so
  // the suite has a verified/hash-match doc (use-freely) beside the
  // seed's placeholder-hash docs (verified/hash-mismatch → warn-user).
  const machine = await readFile(
    path.join(kb.seedClone, "systems", "drill", "shop", "customers.schema.md"),
    "utf-8",
  );
  const { fm } = parseFrontMatter(machine);
  const realHash = String(fm?.schema_hash ?? "");
  const customersPath = path.join(kb.seedClone, "systems", "drill", "shop", "customers.md");
  const customers = await readFile(customersPath, "utf-8");
  await writeFile(
    customersPath,
    customers.replace(/^written_against_schema_hash: .*$/m, `written_against_schema_hash: "${realHash}"`),
  );

  kb.commitAll("mcp rig: seed KB");

  const core = await startCore({
    sync: syncConfig(kb, path.join(base, "sync-workdir")),
    mcp: {
      enabled: true,
      publicUrl: "http://127.0.0.1:0",
      oidcIssuer: idp.issuer,
      oidcClientId: "core",
      oidcClientSecret: "core-secret",
      rolesClaim: "roles",
      kbRefreshMs: 0,
      vtokenTtlS: 300,
      limits: {
        readPerMin: 1000,
        validatePerMin: 1000,
        executePerMin: 1000,
        publishPerHour: 1000,
        flagPerSession: 1000,
        ...overrides.limits,
      },
      ledgerRetentionDays: 90,
      ledgerSweepMs: 60 * 60 * 1000,
    },
  });
  await insertAcceptedSnapshot(core, drill);
  await insertAcceptedSnapshot(core, ga4);

  return {
    core,
    kb,
    idp,
    drill,
    ga4,
    base: core.baseUrl,
    token: (user) => idp.passwordToken(USERS[user].username),
    stop: async () => {
      await core.stop();
      await idp.close();
    },
  };
}

// ---------------------------------------------------------------------------
// Raw streamable-HTTP JSON-RPC client (stateless server: one POST per
// request, initialize not required to precede tool calls)

let rpcId = 1;

export async function mcpRequest(
  rig: McpRig,
  token: string | null,
  profile: string | null,
  method: string,
  params: Record<string, unknown> = {},
): Promise<{ status: number; json: Record<string, unknown> | null; headers: Headers }> {
  const url = new URL(`${rig.base}/mcp`);
  if (profile !== null) url.searchParams.set("profile", profile);
  const response = await fetch(url, {
    method: "POST",
    headers: {
      ...(token !== null ? { authorization: `Bearer ${token}` } : {}),
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({ jsonrpc: "2.0", id: rpcId++, method, params }),
  });
  const text = await response.text();
  let json: Record<string, unknown> | null = null;
  try {
    json = text ? (JSON.parse(text) as Record<string, unknown>) : null;
  } catch {
    // SSE-framed response: extract the data line
    const match = /^data: (.*)$/m.exec(text);
    if (match) json = JSON.parse(match[1]!) as Record<string, unknown>;
  }
  return { status: response.status, json, headers: response.headers };
}

export interface ToolResult {
  status: number;
  isError: boolean;
  payload: Record<string, unknown>;
  rpcError: Record<string, unknown> | null;
}

export async function callTool(
  rig: McpRig,
  token: string,
  profile: string,
  name: string,
  args: Record<string, unknown> = {},
): Promise<ToolResult> {
  const { status, json } = await mcpRequest(rig, token, profile, "tools/call", {
    name,
    arguments: args,
  });
  if (!json || typeof json !== "object" || !("result" in json)) {
    return {
      status,
      isError: true,
      payload: {},
      rpcError: (json?.error as Record<string, unknown>) ?? (json as Record<string, unknown>) ?? null,
    };
  }
  const result = json.result as {
    isError?: boolean;
    content?: { type: string; text: string }[];
  };
  const text = result.content?.[0]?.text ?? "{}";
  return {
    status,
    isError: result.isError === true,
    payload: JSON.parse(text) as Record<string, unknown>,
    rpcError: null,
  };
}

export async function listTools(
  rig: McpRig,
  token: string,
  profile: string,
): Promise<{ status: number; names: string[]; json: Record<string, unknown> | null }> {
  const { status, json } = await mcpRequest(rig, token, profile, "tools/list");
  const tools = ((json?.result as { tools?: { name: string }[] })?.tools ?? []).map((t) => t.name);
  return { status, names: tools.sort(), json };
}

export async function auditRows(
  rig: McpRig,
  where: { tool?: string; decision?: string } = {},
): Promise<Record<string, unknown>[]> {
  const clauses: string[] = [];
  const params: unknown[] = [];
  if (where.tool) {
    params.push(where.tool);
    clauses.push(`tool = $${params.length}`);
  }
  if (where.decision) {
    params.push(where.decision);
    clauses.push(`decision = $${params.length}`);
  }
  const { rows } = await rig.core.pool.query(
    `SELECT * FROM audit_records ${clauses.length ? `WHERE ${clauses.join(" AND ")}` : ""} ORDER BY ts`,
    params,
  );
  return rows;
}
