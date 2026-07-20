/**
 * The M2 execution path end to end (CP-6): MCP `validate_sql` →
 * `execute_sql` → interactive job → real Python runner → real Postgres
 * → rows back to the blocked caller.
 *
 * Nothing here is faked. The source is a real database seeded from the
 * drill DDL (so the accepted snapshot and the live schema genuinely
 * agree), execution runs under a real role holding SELECT and nothing
 * else, and the runner is `connectors.sdk.service` over HTTP.
 *
 * Also carries the **JP-2 measurement** (plan §6.5): p95 claim-to-start
 * over ≥100 warm executes against the committed 500 ms budget, plus
 * end-to-end wall time as a non-normative companion. JP-2 is normatively
 * claim-to-start *excluding query time* (job spec §11), which is why
 * both numbers are recorded rather than one.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { startSweeper } from "../src/server.js";
import { adminUrl, pythonPath, repoRoot, TEST_TOKEN } from "./helpers.js";
import { callTool, setupMcpRig, type McpRig } from "./mcp-helpers.js";

const EXEC_PASSWORD = "cl-exec-e2e-7b1c";
const JP2_SAMPLES = Number(process.env.CL_JP2_SAMPLES ?? 100);

let rig: McpRig;
let runner: { child: ChildProcess; output: () => string; stop: () => Promise<void> };
let stopSweeper: () => void;
let sourceDsn: string;
let execDsn: string;

async function seedSource(): Promise<void> {
  const admin = new pg.Client({ connectionString: adminUrl() });
  await admin.connect();
  await admin.query(`DROP DATABASE IF EXISTS cl_exec_src WITH (FORCE)`);
  await admin.query(`DROP ROLE IF EXISTS cl_exec_e2e`);
  await admin.query(`CREATE DATABASE cl_exec_src`);
  await admin.query(`CREATE ROLE cl_exec_e2e LOGIN PASSWORD '${EXEC_PASSWORD}'`);
  await admin.end();

  const url = new URL(adminUrl());
  url.pathname = "/cl_exec_src";
  sourceDsn = url.toString();

  const seed = new pg.Client({ connectionString: sourceDsn });
  await seed.connect();
  // Same shape the accepted `drill` snapshot describes.
  await seed.query(`
    CREATE SCHEMA shop;
    CREATE SCHEMA reporting;
    CREATE TABLE shop.customers (id bigint PRIMARY KEY, email text NOT NULL, name text);
    CREATE TABLE shop.orders (
      id bigint PRIMARY KEY,
      customer_id bigint NOT NULL REFERENCES shop.customers (id),
      status text NOT NULL DEFAULT 'new',
      net numeric(12,2) NOT NULL,
      discount numeric(12,2),
      created_at timestamptz NOT NULL DEFAULT now());
    INSERT INTO shop.customers (id, email, name)
      SELECT i, 'user' || i || '@example.com', 'User ' || i FROM generate_series(1, 250) i;
    INSERT INTO shop.orders (id, customer_id, net)
      SELECT i, 1 + (i % 250), (i * 3)::numeric FROM generate_series(1, 400) i;
  `);
  // The execution role: SELECT only, no CREATE, not a superuser (G3).
  await seed.query(`
    GRANT USAGE ON SCHEMA shop, reporting TO cl_exec_e2e;
    GRANT SELECT ON ALL TABLES IN SCHEMA shop TO cl_exec_e2e;
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    REVOKE CREATE ON SCHEMA shop, reporting FROM PUBLIC;
  `);
  await seed.end();

  const exec = new URL(sourceDsn);
  exec.username = "cl_exec_e2e";
  exec.password = EXEC_PASSWORD;
  execDsn = exec.toString();
}

async function spawnRunner() {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-exec-runner-"));
  const configFile = path.join(dir, "runner.yaml");
  await writeFile(
    configFile,
    JSON.stringify({
      core_url: rig.core.baseUrl,
      token_env: "CL_RUNNER_TOKEN",
      runner_id: "runner-exec",
      connectors: ["connectors.postgres.connector:connector"],
      // The interactive lane is what M2 adds.
      classes: ["batch", "interactive"],
      wait_s: 2,
      claim_backoff_s: 0.5,
      resolver: { kind: "process-env" },
      execution_preflight: [
        { connector: "postgres", config: { system: "drill", execute_dsn_env: "CL_EXEC_DSN" } },
      ],
    }),
  );
  let captured = "";
  const child = spawn(
    pythonPath(),
    ["-m", "connectors.sdk.service", "--config", configFile, "-v"],
    {
      cwd: repoRoot(),
      env: {
        ...process.env,
        PYTHONPATH: repoRoot(),
        PYTHONUNBUFFERED: "1",
        CL_RUNNER_TOKEN: TEST_TOKEN,
        CL_EXEC_DSN: execDsn,
      },
    },
  );
  child.stdout!.on("data", (d: Buffer) => (captured += d.toString()));
  child.stderr!.on("data", (d: Buffer) => (captured += d.toString()));
  const exited = new Promise<void>((resolve) => child.on("exit", () => resolve()));
  return {
    child,
    output: () => captured,
    stop: async () => {
      child.kill("SIGKILL");
      await exited;
    },
  };
}

beforeAll(async () => {
  rig = await setupMcpRig();
  await seedSource();

  // Register the connection the gateway resolves for `drill`. The
  // credential is a reference (J-4); the runner resolves it.
  await rig.core.pool.query(
    `INSERT INTO sync_systems (system, connector_name, version_constraint, payload)
     VALUES ($1, $2, $3, $4::jsonb)
     ON CONFLICT (system) DO UPDATE SET payload = excluded.payload`,
    [
      "drill",
      "postgres",
      ">=0.2 <0.3",
      JSON.stringify({
        config: { system: "drill", mode: "live" },
        credentials: [
          // `required_for` scopes this to the query capability; the
          // introspection DSN is deliberately not in this registration.
          { ref: "env://CL_EXEC_DSN", key: "execute_dsn", required_for: ["query"] },
        ],
      }),
    ],
  );

  stopSweeper = startSweeper(rig.core.pool, rig.core.cfg, () => {});
  runner = await spawnRunner();
}, 300_000);

afterAll(async () => {
  stopSweeper?.();
  await runner?.stop();
  await rig?.stop();
});

async function validate(statement: string) {
  return callTool(rig, rig.token("steward"), "steward", "validate_sql", {
    system: "drill",
    request: { dialect: "sql", statement },
  });
}

async function validateAndExecute(statement: string, extra: Record<string, unknown> = {}) {
  const validated = await validate(statement);
  expect(validated.payload.verdict, JSON.stringify(validated.payload.findings)).toBe("pass");
  return callTool(rig, rig.token("steward"), "steward", "execute_sql", {
    system: "drill",
    request: { dialect: "sql", statement },
    validation_token: validated.payload.validation_token,
    ...extra,
  });
}

describe("execute_sql end to end (§6.7, capability §6)", () => {
  it("a validated SELECT returns real rows through the queue", async () => {
    const result = await validateAndExecute(
      "SELECT count(*) AS n FROM shop.customers",
      { intent: "how many customers do we have" },
    );
    expect(result.isError, JSON.stringify(result.payload)).toBe(false);
    expect(result.payload.columns).toEqual([{ name: "n", type: "int8" }]);
    expect(result.payload.rows).toEqual([[250]]);
    expect(result.payload.truncated).toBe(false);
    expect((result.payload.source as { executed_on: string }).executed_on).toBe("primary");
    // M-5: every response carries refs.
    expect(result.payload.refs).toBeTruthy();
  }, 60_000);

  it("the audit record carries the full statement and the row count", async () => {
    const statement = "SELECT id, email FROM shop.customers ORDER BY id LIMIT 3";
    const result = await validateAndExecute(statement);
    expect(result.isError).toBe(false);

    const { rows } = await rig.core.pool.query<{
      statement_text: string;
      result_meta: Record<string, unknown>;
      decision: string;
    }>(
      `SELECT statement_text, result_meta, decision FROM audit_records
        WHERE tool = 'execute_sql' AND statement_text = $1
        ORDER BY ts DESC LIMIT 1`,
      [statement],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0]!.decision).toBe("allowed");
    expect(rows[0]!.result_meta.rows).toBe(3);
    expect(rows[0]!.result_meta.job_id).toBeTruthy();
  }, 60_000);

  it("the executed statement carries the QE-2 identity comment tag", async () => {
    await validateAndExecute("SELECT 1 AS tagged", { intent: "tag check" });
    // The runner logs the execute; the tag itself was asserted against
    // Postgres' own statement log in the Python suite (CC-5). Here the
    // evidence is that the subject reached the runner at all.
    expect(runner.output()).toContain("subject=alper-steward");
  }, 60_000);

  it("a result within the cap is not flagged truncated", async () => {
    const result = await validateAndExecute("SELECT id FROM shop.orders ORDER BY id");
    expect(result.isError).toBe(false);
    expect((result.payload.rows as unknown[]).length).toBe(400);
    expect(result.payload.truncated).toBe(false);
  }, 60_000);

  it("an over-cap query truncates at the profile's row_cap (CI-7)", async () => {
    // The `capped` profile's row_cap is 5; the source has 400 orders.
    // The cap is the *profile's*, injected server-side — the caller
    // asked for everything and cannot opt out.
    const statement = "SELECT id FROM shop.orders ORDER BY id";
    const validated = await callTool(rig, rig.token("capped"), "capped", "validate_sql", {
      system: "drill",
      request: { dialect: "sql", statement },
    });
    expect(validated.payload.verdict).toBe("pass");

    const result = await callTool(rig, rig.token("capped"), "capped", "execute_sql", {
      system: "drill",
      request: { dialect: "sql", statement },
      validation_token: validated.payload.validation_token,
    });
    expect(result.isError, JSON.stringify(result.payload)).toBe(false);
    expect((result.payload.rows as unknown[]).length).toBe(5);
    // CI-7: truncation is an explicit fact, never silent.
    expect(result.payload.truncated).toBe(true);
    expect(result.payload.row_count).toBe(5);
  }, 60_000);

  it("a CTE-wrapped write is refused at validate — it never reaches execute", async () => {
    const validated = await validate(
      "WITH w AS (DELETE FROM shop.orders RETURNING id) SELECT count(*) FROM w",
    );
    expect(validated.payload.verdict).toBe("fail");
    expect(validated.payload.validation_token).toBeUndefined();

    // And the estate is untouched.
    const check = await validateAndExecute("SELECT count(*) AS n FROM shop.orders");
    expect(check.payload.rows).toEqual([[400]]);
  }, 60_000);

  it("a statement referencing a dropped object surfaces schema_mismatch and files a ledger event", async () => {
    // Validate against the snapshot (which has the table), then drop it
    // live — the validate/execute race, deterministically staged.
    const statement = "SELECT id FROM shop.legacy_sessions";
    const validated = await validate(statement);
    expect(validated.payload.verdict).toBe("pass");

    const admin = new pg.Client({ connectionString: sourceDsn });
    await admin.connect();
    await admin.query(`CREATE TABLE IF NOT EXISTS shop.legacy_sessions (id bigint PRIMARY KEY)`);
    await admin.query(`DROP TABLE shop.legacy_sessions`);
    await admin.end();

    const result = await callTool(rig, rig.token("steward"), "steward", "execute_sql", {
      system: "drill",
      request: { dialect: "sql", statement },
      validation_token: validated.payload.validation_token,
    });
    expect(result.isError).toBe(true);
    expect((result.payload.detail as { capability_code: string }).capability_code).toBe(
      "schema_mismatch",
    );

    const { rows } = await rig.core.pool.query<{ n: string }>(
      `SELECT count(*) AS n FROM ledger_events
        WHERE detail->>'rule' = 'schema_mismatch_at_execute'`,
    );
    expect(Number(rows[0]!.n)).toBeGreaterThan(0);
  }, 60_000);
});

describe("JP-2 — interactive latency (job spec §11, plan §6.5)", () => {
  it(`p95 claim-to-start over ${JP2_SAMPLES} warm executes is within the 500 ms budget`, async () => {
    const statement = "SELECT 1 AS warm";
    // Warm the path: connection pools, the runner's claim loop, and the
    // sqlval process are all cold on the first call and would otherwise
    // dominate the sample.
    for (let i = 0; i < 5; i += 1) await validateAndExecute(statement);

    const endToEnd: number[] = [];
    const jobIds: string[] = [];
    for (let i = 0; i < JP2_SAMPLES; i += 1) {
      const started = Date.now();
      const result = await validateAndExecute(statement);
      endToEnd.push(Date.now() - started);
      expect(result.isError).toBe(false);
      jobIds.push((result.payload as never as { refs: unknown }) && (await lastJobId()));
    }

    // JP-2 as specified: claim-to-start overhead, excluding query time.
    // created_at → started_at is exactly that window (enqueue to the
    // runner's `start` call).
    const { rows } = await rig.core.pool.query<{ ms: number }>(
      `SELECT EXTRACT(EPOCH FROM (started_at - created_at)) * 1000 AS ms
         FROM jobs
        WHERE type = 'execute' AND started_at IS NOT NULL AND job_id = ANY($1)
        ORDER BY created_at`,
      [jobIds],
    );
    const claimToStart = rows.map((r) => Number(r.ms)).filter((n) => Number.isFinite(n));
    expect(claimToStart.length).toBeGreaterThanOrEqual(JP2_SAMPLES * 0.9);

    const quantile = (xs: number[], q: number) => {
      const sorted = [...xs].sort((a, b) => a - b);
      return sorted[Math.min(sorted.length - 1, Math.max(0, Math.ceil(sorted.length * q) - 1))]!;
    };
    const claimP95 = quantile(claimToStart, 0.95);
    const e2eP95 = quantile(endToEnd, 0.95);

    // Recorded for DECISIONS (plan §6.5 / JP-1 disposition).
    console.log(
      `[JP-2] n=${claimToStart.length} claim-to-start p50=${quantile(claimToStart, 0.5).toFixed(1)}ms ` +
        `p95=${claimP95.toFixed(1)}ms max=${Math.max(...claimToStart).toFixed(1)}ms | ` +
        `end-to-end p50=${quantile(endToEnd, 0.5).toFixed(1)}ms p95=${e2eP95.toFixed(1)}ms (non-normative)`,
    );

    expect(claimP95).toBeLessThanOrEqual(500);
  }, 600_000);
});

async function lastJobId(): Promise<string> {
  const { rows } = await rig.core.pool.query<{ job_id: string }>(
    `SELECT job_id FROM jobs WHERE type = 'execute' ORDER BY created_at DESC LIMIT 1`,
  );
  return rows[0]!.job_id;
}
