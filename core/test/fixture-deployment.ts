/**
 * Standalone fixture deployment for the CP-5 behavioral scenarios
 * (skill-spec §9, ruling D-78 layer (b)).
 *
 * The in-process MCP rig (`setupMcpRig`) already assembles exactly what
 * §9 asks for — fixture KB, fixture snapshots, stub connectors, a dev
 * IdP, the contaminated `legacy_sessions` doc — but as a vitest fixture
 * that dies with the test process. This wraps it so an *external* Claude
 * Code agent can connect: it stands the rig up, writes a connection file
 * (base URL, per-user bearer tokens, the ops DB URL for audit reads), and
 * stays alive until signalled.
 *
 *   node_modules/.bin/vite-node test/fixture-deployment.ts -- \
 *       --out CONNECTION.json [--with-execution]
 *
 * `--with-execution` additionally seeds the `drill` source database, wires
 * the postgres connector under a SELECT-only role, and spawns a real
 * runner on the interactive lane — the same machinery `execute-e2e.test.ts`
 * uses. The report scenario (AS-10) needs the real execution loop; the two
 * enrich scenarios (AS-9, AS-12) do not, so it is opt-in.
 *
 * Test infrastructure, not a product surface: it mints tokens with a dev
 * IdP and must never point at anything but the fixture.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import { startSweeper } from "../src/server.js";
import { adminUrl, pythonPath, repoRoot, TEST_TOKEN } from "./helpers.js";
import { setupMcpRig, USERS, type McpRig } from "./mcp-helpers.js";

const EXEC_PASSWORD = "test-only-exec-password";

/** Seed a `drill`-shaped source DB and return the SELECT-only exec DSN. */
async function seedSource(): Promise<string> {
  const admin = new pg.Client({ connectionString: adminUrl() });
  await admin.connect();
  await admin.query(`DROP DATABASE IF EXISTS cl_fixture_src WITH (FORCE)`);
  await admin.query(`DROP ROLE IF EXISTS cl_fixture_exec`);
  await admin.query(`CREATE DATABASE cl_fixture_src`);
  await admin.query(`CREATE ROLE cl_fixture_exec LOGIN PASSWORD '${EXEC_PASSWORD}'`);
  await admin.end();

  const url = new URL(adminUrl());
  url.pathname = "/cl_fixture_src";
  const sourceDsn = url.toString();

  const seed = new pg.Client({ connectionString: sourceDsn });
  await seed.connect();
  // The shape the accepted `drill` snapshot describes.
  // The full `drill` shape the snapshot describes, including the
  // reporting views the certified net-sales metric chain reads — the
  // report scenario (AS-10) resolves that metric and must be able to
  // actually execute it, not just reach execute_sql.
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
    CREATE TABLE shop.order_items (
      id bigint PRIMARY KEY,
      order_id bigint NOT NULL REFERENCES shop.orders (id),
      sku text NOT NULL,
      qty integer NOT NULL,
      price numeric(12,2) NOT NULL);
    CREATE TABLE shop.legacy_sessions (
      id bigint PRIMARY KEY, visitor_id text NOT NULL, started_at timestamptz NOT NULL);
    CREATE VIEW reporting.v_order_totals AS
      SELECT o.id AS order_id, o.customer_id, sum(i.qty * i.price) AS items_total
        FROM shop.orders o JOIN shop.order_items i ON i.order_id = o.id
       GROUP BY o.id, o.customer_id;
    CREATE VIEW reporting.v_net_sales AS
      SELECT t.customer_id, sum(t.items_total) AS net_total
        FROM reporting.v_order_totals t GROUP BY t.customer_id;
    INSERT INTO shop.customers (id, email, name)
      SELECT i, 'user' || i || '@example.com', 'User ' || i FROM generate_series(1, 250) i;
    INSERT INTO shop.orders (id, customer_id, net)
      SELECT i, 1 + (i % 250), (i * 3)::numeric FROM generate_series(1, 400) i;
    INSERT INTO shop.order_items (id, order_id, sku, qty, price)
      SELECT i, 1 + (i % 400), 'sku-' || (i % 20), 1 + (i % 5), (10 + (i % 90))::numeric
      FROM generate_series(1, 1200) i;
  `);
  await seed.query(`
    GRANT USAGE ON SCHEMA shop, reporting TO cl_fixture_exec;
    GRANT SELECT ON ALL TABLES IN SCHEMA shop TO cl_fixture_exec;
    GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO cl_fixture_exec;
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    REVOKE CREATE ON SCHEMA shop, reporting FROM PUBLIC;
  `);
  await seed.end();

  const exec = new URL(sourceDsn);
  exec.username = "cl_fixture_exec";
  exec.password = EXEC_PASSWORD;
  return exec.toString();
}

async function spawnRunner(rig: McpRig, execDsn: string): Promise<{ stop: () => Promise<void> }> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-fixture-runner-"));
  const configFile = path.join(dir, "runner.yaml");
  await writeFile(
    configFile,
    JSON.stringify({
      core_url: rig.core.baseUrl,
      token_env: "CL_RUNNER_TOKEN",
      runner_id: "runner-fixture",
      connectors: ["connectors.postgres.connector:connector"],
      classes: ["batch", "interactive"],
      wait_s: 2,
      claim_backoff_s: 0.5,
      resolver: { kind: "process-env" },
      execution_preflight: [
        { connector: "postgres", config: { system: "drill", execute_dsn_env: "CL_EXEC_DSN" } },
      ],
    }),
  );
  const child: ChildProcess = spawn(
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
  const exited = new Promise<void>((resolve) => child.on("exit", () => resolve()));
  return {
    stop: async () => {
      child.kill("SIGKILL");
      await exited;
    },
  };
}

async function main(): Promise<void> {
  const outIdx = process.argv.indexOf("--out");
  const outPath = outIdx >= 0 ? process.argv[outIdx + 1] : null;
  const withExecution = process.argv.includes("--with-execution");
  if (!outPath) {
    console.error("usage: fixture-deployment.js --out CONNECTION.json [--with-execution]");
    process.exit(2);
  }

  // B-1: the dashboard surface is up too, because the enrich skill's
  // queue-driven mode (S1b/AS-18) reads its delivered batch through the
  // governed ledger API as the session user — the same identity the MCP
  // tools carry, over the same verifier. A fixture without it could not
  // exercise the mode at all.
  const rig = await setupMcpRig({ dashboard: { enabled: true } });

  let stopSweeper: () => void = () => {};
  let runner: { stop: () => Promise<void> } | null = null;
  if (withExecution) {
    const execDsn = await seedSource();
    // Register the connection the gateway resolves for `drill`.
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
          credentials: [{ ref: "env://CL_EXEC_DSN", key: "execute_dsn", required_for: ["query"] }],
        }),
      ],
    );
    stopSweeper = startSweeper(rig.core.pool, rig.core.cfg, () => {});
    runner = await spawnRunner(rig, execDsn);
    console.error("execution wired: drill source seeded, runner up on the interactive lane");
  }

  const tokens: Record<string, string> = {};
  for (const user of Object.keys(USERS) as (keyof typeof USERS)[]) {
    tokens[user] = rig.token(user);
  }

  const connection = {
    base: rig.base,
    mcp_url: `${rig.base}/mcp`,
    // The governed API root the S1b batch is read from.
    core_url: rig.base,
    ops_db_url: rig.core.cfg.databaseUrl,
    kb_dir: rig.kb.seedClone,
    execution: withExecution,
    tokens,
    users: Object.fromEntries(
      Object.entries(USERS).map(([k, v]) => [k, { roles: v.roles, display: v.display }]),
    ),
  };

  await writeFile(outPath, `${JSON.stringify(connection, null, 2)}\n`);
  console.error(`fixture deployment up at ${rig.base} — connection written to ${outPath}`);
  console.error("SIGINT/SIGTERM to tear down.");

  let stopping = false;
  const shutdown = async () => {
    if (stopping) return;
    stopping = true;
    console.error("tearing down fixture deployment…");
    stopSweeper();
    await runner?.stop();
    await rig.stop();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  setInterval(() => {}, 1 << 30);
}

main().catch((err) => {
  console.error("fixture deployment failed to start", err);
  process.exit(1);
});
