/**
 * End-to-end over real processes: the TypeScript core (this package) and
 * the real Python SDK runner (`connectors.sdk.service`) hosting real
 * connectors.
 *
 * - fixture pipeline: enqueue → claim → execute → deliver → J-6 →
 *   accepted snapshot, byte-compared against the local CLI harness
 *   (C-2 across the transport);
 * - JC-8: a canary secret resolved by the runner (postgres live DSN)
 *   appears in no protocol message, log line, or stored row;
 * - JC-4 + the two-replica exit criterion: SIGKILL a runner mid-job →
 *   lease expiry → a second runner reclaims and delivers an identical
 *   canonical body.
 */

import assert from "node:assert/strict";
import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import { afterAll, beforeAll, expect, it } from "vitest";
import { startSweeper } from "../src/server.js";
import { WireClient } from "./fake-runner.js";
import {
  acceptVerdict,
  adminUrl,
  cliHarnessSnapshot,
  pythonPath,
  repoRoot,
  sleep,
  startCore,
  TEST_OPS_TOKEN,
  TEST_TOKEN,
  type TestCore,
} from "./helpers.js";

const CANARY_PASSWORD = "test-only-canary-password";

let core: TestCore;
let client: WireClient;
let stopSweeper: () => void;
let canaryDsn: string;

interface RunnerProc {
  child: ChildProcess;
  output: () => string;
  kill: (signal?: NodeJS.Signals) => void;
  waitExit: () => Promise<void>;
}

async function spawnRunner(
  runnerId: string,
  connectors: string[],
  env: Record<string, string> = {},
): Promise<RunnerProc> {
  const dir = await mkdtemp(path.join(tmpdir(), `cl-runner-${runnerId}-`));
  const configFile = path.join(dir, "runner.yaml");
  // YAML is a JSON superset, so the config can be written as JSON.
  await writeFile(
    configFile,
    JSON.stringify({
      core_url: core.baseUrl,
      token_env: "CL_RUNNER_TOKEN",
      runner_id: runnerId,
      connectors,
      classes: ["batch"],
      wait_s: 2,
      claim_backoff_s: 0.5,
      resolver: { kind: "process-env" },
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
        ...env,
      },
    },
  );
  child.stdout!.on("data", (d: Buffer) => (captured += d.toString()));
  child.stderr!.on("data", (d: Buffer) => (captured += d.toString()));
  const exited = new Promise<void>((resolve) => child.on("exit", () => resolve()));
  return {
    child,
    output: () => captured,
    kill: (signal: NodeJS.Signals = "SIGKILL") => child.kill(signal),
    waitExit: () => exited,
  };
}

let runnerA: RunnerProc;
let runnerB: RunnerProc | null = null;

beforeAll(async () => {
  core = await startCore({ leaseTtlS: 2, sweepIntervalMs: 200 });
  client = new WireClient(core.baseUrl, TEST_TOKEN, TEST_OPS_TOKEN);
  stopSweeper = startSweeper(core.pool, core.cfg, () => {});

  // Canary source: a real database on the test server, reachable only
  // through a role whose password is the canary secret.
  const admin = new pg.Client({ connectionString: adminUrl() });
  await admin.connect();
  await admin.query(`DROP DATABASE IF EXISTS cl_canary_src WITH (FORCE)`);
  await admin.query(`CREATE DATABASE cl_canary_src`);
  await admin.query(`DROP ROLE IF EXISTS cl_canary_user`);
  await admin.query(`CREATE ROLE cl_canary_user LOGIN PASSWORD '${CANARY_PASSWORD}'`);
  await admin.end();
  const src = new URL(adminUrl());
  src.pathname = "/cl_canary_src";
  const seed = new pg.Client({ connectionString: src.toString() });
  await seed.connect();
  await seed.query(
    `CREATE TABLE public.widgets (
       id integer PRIMARY KEY,
       name text NOT NULL,
       created_at timestamptz NOT NULL DEFAULT now())`,
  );
  await seed.end();
  canaryDsn =
    `postgres://cl_canary_user:${CANARY_PASSWORD}@${src.hostname}:${src.port}/cl_canary_src`;

  runnerA = await spawnRunner(
    "runner-a1",
    [
      "connectors.static_demo.connector:connector",
      "tests.job_fixtures.slow_demo:connector",
      "connectors.postgres.connector:connector",
    ],
    { CANARY_DSN: canaryDsn },
  );
}, 120_000);

afterAll(async () => {
  stopSweeper();
  runnerA?.kill();
  runnerB?.kill();
  await Promise.all([runnerA?.waitExit(), runnerB?.waitExit()]);
  await core.stop();
});

it("fixture e2e: enqueue → runner → J-6 → accepted snapshot, byte-equal to the CLI harness", async () => {
  const { status, json } = await client.enqueue({
    type: "snapshot",
    system: "demo-e2e",
    connector: { name: "static-demo", version_constraint: ">=0.1 <0.2" },
    payload: { config: { system: "demo-e2e", mode: "ddl-file" } },
    trigger: { kind: "manual", detail: "e2e" },
  });
  expect(status).toBe(201);
  const job = await client.waitForState(json.job_id as string, ["succeeded", "dead_lettered"], 60_000);
  expect(job.state).toBe("succeeded");
  const meta = job.result_meta as { snapshot_id: string; canonical_body_sha256: string };

  const stored = await fetch(`${core.baseUrl}/v1/snapshots/${meta.snapshot_id}/body`, {
    headers: { authorization: `Bearer ${TEST_OPS_TOKEN}` },
  });
  const deliveredBytes = Buffer.from(await stored.arrayBuffer());

  const cliBytes = await cliHarnessSnapshot("connectors.static_demo.connector:connector", {
    system: "demo-e2e",
    mode: "ddl-file",
  });

  // Full documents agree except the per-run capture timestamp…
  const delivered = JSON.parse(deliveredBytes.toString("utf-8")) as Record<string, unknown>;
  const reference = JSON.parse(cliBytes.toString("utf-8")) as Record<string, unknown>;
  delete delivered.captured_at;
  delete reference.captured_at;
  assert.deepStrictEqual(delivered, reference);

  // …and the canonical bodies (the S-3 diff identity) are byte-identical.
  const referenceVerdict = await acceptVerdict(cliBytes);
  expect(meta.canonical_body_sha256).toBe(referenceVerdict.canonical_body_sha256);
}, 90_000);

it("JC-8: canary secret appears in no protocol message, log, or stored row", async () => {
  const { status, json } = await client.enqueue({
    type: "snapshot",
    system: "supabase-canary",
    connector: { name: "postgres", version_constraint: ">=0.1 <0.2" },
    payload: {
      config: { system: "supabase-canary", mode: "live" },
      credentials: [{ ref: "env://CANARY_DSN", key: "dsn" }],
    },
    trigger: { kind: "manual", detail: "jc8" },
  });
  expect(status).toBe(201);
  const job = await client.waitForState(json.job_id as string, ["succeeded", "dead_lettered"], 60_000);
  expect(job.state, JSON.stringify(job.error)).toBe("succeeded");

  // the introspection is real: the widgets table came through
  const meta = job.result_meta as { snapshot_id: string };
  const stored = await fetch(`${core.baseUrl}/v1/snapshots/${meta.snapshot_id}/body`, {
    headers: { authorization: `Bearer ${TEST_OPS_TOKEN}` },
  });
  const body = Buffer.from(await stored.arrayBuffer()).toString("utf-8");
  expect(body).toContain('"name":"widgets"');

  // canary sweep: ops rows, snapshot body, core logs, runner logs
  const { rows } = await core.pool.query(
    `SELECT (SELECT coalesce(string_agg(jobs::text, ''), '') FROM jobs) ||
            (SELECT coalesce(string_agg(health_events::text, ''), '') FROM health_events) ||
            (SELECT coalesce(string_agg(convert_from(body, 'utf-8'), ''), '')
               FROM accepted_snapshots) AS blob`,
  );
  expect(rows[0].blob).not.toContain(CANARY_PASSWORD);
  expect(body).not.toContain(CANARY_PASSWORD);
  expect(core.logs()).not.toContain(CANARY_PASSWORD);
  expect(runnerA.output()).not.toContain(CANARY_PASSWORD);

  // the stored payload carries the reference, never the resolved value
  const payload = JSON.stringify(job.payload);
  expect(payload).toContain("env://CANARY_DSN");
  expect(payload).not.toContain(CANARY_PASSWORD);
}, 90_000);

it("JC-4: runner killed mid-job → reclaim by a second runner → identical canonical body", async () => {
  const { json } = await client.enqueue({
    type: "snapshot",
    system: "slow-e2e",
    connector: { name: "slow-demo", version_constraint: "*" },
    payload: { config: { system: "slow-e2e", mode: "ddl-file", sleep_s: 6 } },
    trigger: { kind: "manual", detail: "jc4" },
  });
  const jobId = json.job_id as string;

  await client.waitForState(jobId, ["running"], 30_000);
  runnerA.kill("SIGKILL");

  // lease (2 s) expires; sweeper (200 ms) requeues with attempt+1
  const requeued = await client.waitForState(jobId, ["queued"], 15_000);
  expect(requeued.attempt).toBe(2);

  runnerB = await spawnRunner("runner-b1", ["tests.job_fixtures.slow_demo:connector"]);
  const done = await client.waitForState(jobId, ["succeeded", "dead_lettered"], 60_000);
  expect(done.state, JSON.stringify(done.error)).toBe("succeeded");
  expect(done.runner_id).toBe("runner-b1");

  const meta = done.result_meta as { canonical_body_sha256: string };
  const cliBytes = await cliHarnessSnapshot("tests.job_fixtures.slow_demo:connector", {
    system: "slow-e2e",
    mode: "ddl-file",
    sleep_s: 0,
  });
  const referenceVerdict = await acceptVerdict(cliBytes);
  expect(meta.canonical_body_sha256).toBe(referenceVerdict.canonical_body_sha256);

  const events = (await client.get(`/v1/health-events?job_id=${jobId}`)).json
    .events as Record<string, unknown>[];
  expect(events.some((e) => e.kind === "lease_expired")).toBe(true);
}, 120_000);
