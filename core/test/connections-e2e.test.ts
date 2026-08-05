/**
 * A-3, end to end against a real source and a real runner.
 *
 * The other connections suite proves the API's shape. This one proves
 * the thing the gate actually promises an operator: pressing **Test
 * connection** reaches the source. A `test_connection` job is enqueued
 * by the API, claimed by a live SDK runner, resolved through the ordinary
 * credential seam, and executed by the connector's own preflight
 * surfaces — the same code a snapshot job runs first.
 *
 * Both verdicts are exercised against the same live Postgres:
 *
 *   - a good credential → `pass`, with the role facts the probe read;
 *   - a wrong password → `auth_error` → the re-auth prompt, naming the
 *     *reference* whose value needs attention and never a value.
 *
 * The second half is why this file exists. An auth_error that is only
 * ever simulated is an auth_error nobody has watched the product handle.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { startSweeper } from "../src/server.js";
import { adminUrl, pythonPath, repoRoot, TEST_TOKEN } from "./helpers.js";
import {
  apiGet,
  apiPost,
  login,
  setupDashboardRig,
  type BrowserSession,
  type DashboardRig,
} from "./dashboard-helpers.js";

const RO_PASSWORD = "cl-probe-ro-3f2a";
const EXEC_PASSWORD = "cl-probe-exec-9d4b";

let rig: DashboardRig;
let admin: BrowserSession;
let runner: { child: ChildProcess; output: () => string; stop: () => Promise<void> };
let stopSweeper: () => void;
let roDsn: string;
let execDsn: string;
let wrongDsn: string;

/** PUT as the admin's cookie session. */
async function put(path_: string, body: unknown) {
  const response = await fetch(`${rig.base}${path_}`, {
    method: "PUT",
    headers: {
      cookie: admin.cookie,
      "x-cl-csrf": admin.csrf,
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
  const text = await response.text();
  return { status: response.status, json: text ? JSON.parse(text) : {} };
}

async function seedSource(): Promise<void> {
  const client = new pg.Client({ connectionString: adminUrl() });
  await client.connect();
  await client.query(`DROP DATABASE IF EXISTS cl_probe_src WITH (FORCE)`);
  await client.query(`DROP ROLE IF EXISTS cl_probe_ro`);
  await client.query(`DROP ROLE IF EXISTS cl_probe_exec`);
  await client.query(`CREATE DATABASE cl_probe_src`);
  // Neither role is a superuser and neither holds BYPASSRLS — which is
  // exactly what the metadata preflight checks (D-71.2).
  await client.query(`CREATE ROLE cl_probe_ro LOGIN PASSWORD '${RO_PASSWORD}'`);
  await client.query(`CREATE ROLE cl_probe_exec LOGIN PASSWORD '${EXEC_PASSWORD}'`);
  await client.end();

  const url = new URL(adminUrl());
  url.pathname = "/cl_probe_src";

  const seed = new pg.Client({ connectionString: url.toString() });
  await seed.connect();
  await seed.query(`
    CREATE SCHEMA shop;
    CREATE TABLE shop.customers (id bigint PRIMARY KEY, email text NOT NULL);
    GRANT USAGE ON SCHEMA shop TO cl_probe_ro, cl_probe_exec;
    GRANT SELECT ON ALL TABLES IN SCHEMA shop TO cl_probe_ro, cl_probe_exec;
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    REVOKE CREATE ON SCHEMA shop FROM PUBLIC;
  `);
  await seed.end();

  const ro = new URL(url.toString());
  ro.username = "cl_probe_ro";
  ro.password = RO_PASSWORD;
  roDsn = ro.toString();

  const exec = new URL(url.toString());
  exec.username = "cl_probe_exec";
  exec.password = EXEC_PASSWORD;
  execDsn = exec.toString();

  const wrong = new URL(roDsn);
  wrong.password = "not-the-password";
  wrongDsn = wrong.toString();
}

async function spawnRunner() {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-probe-runner-"));
  const configFile = path.join(dir, "runner.yaml");
  await writeFile(
    configFile,
    JSON.stringify({
      core_url: rig.core.baseUrl,
      token_env: "CL_RUNNER_TOKEN",
      runner_id: "runner-probe",
      connectors: ["connectors.postgres.connector:connector"],
      classes: ["batch", "interactive"],
      wait_s: 2,
      claim_backoff_s: 0.5,
      resolver: { kind: "process-env" },
    }),
  );
  let captured = "";
  const child = spawn(pythonPath(), ["-m", "connectors.sdk.service", "--config", configFile, "-v"], {
    cwd: repoRoot(),
    env: {
      ...process.env,
      PYTHONPATH: repoRoot(),
      PYTHONUNBUFFERED: "1",
      CL_RUNNER_TOKEN: TEST_TOKEN,
      CL_PROBE_DSN: roDsn,
      CL_PROBE_EXEC_DSN: execDsn,
      CL_PROBE_WRONG_DSN: wrongDsn,
    },
  });
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
  rig = await setupDashboardRig({ dashboard: { probeTimeoutS: 45 } });
  admin = await login(rig, "steward");
  await seedSource();
  stopSweeper = startSweeper(rig.core.pool, rig.core.cfg, () => {});
  runner = await spawnRunner();
}, 300_000);

afterAll(async () => {
  stopSweeper?.();
  await runner?.stop();
  await rig?.stop();
});

describe("A-3 test-connection, live", () => {
  it("a healthy connection probes green, through the same credential seam a snapshot uses", async () => {
    const registered = await put("/v1/dashboard/connections/probe", {
      connector: { name: "postgres", version_constraint: ">=0.2 <0.3" },
      payload: {
        // No DSN anywhere in this body — only the names of the places
        // the runner's resolver will look.
        config: { system: "probe", mode: "live" },
        credentials: [
          { key: "dsn", ref: "env://CL_PROBE_DSN", required_for: ["live"] },
          { key: "execute_dsn", ref: "env://CL_PROBE_EXEC_DSN", required_for: ["query"] },
        ],
      },
    });
    expect(registered.status).toBe(201);

    const result = await apiPost(rig, admin, "/v1/dashboard/connections/probe/test", {});
    expect(result.status).toBe(200);
    expect(result.json.outcome, JSON.stringify(result.json)).toBe("pass");

    const checks = result.json.checks as { capability: string; status: string; facts?: Record<string, unknown> }[];
    const byCapability = Object.fromEntries(checks.map((c) => [c.capability, c]));
    expect(byCapability.config!.status).toBe("pass");

    // The metadata preflight connected as the introspection role and
    // read it back — the same check that guards every live snapshot.
    expect(byCapability.metadata!.status).toBe("pass");
    expect(byCapability.metadata!.facts).toMatchObject({
      probed: true,
      mode: "live",
      credential_tested: true,
      role: "cl_probe_ro",
      superuser: false,
      bypassrls: false,
    });

    // The query preflight proved the execution role cannot write (G3).
    expect(byCapability.query!.status).toBe("pass");
    expect(byCapability.query!.facts).toMatchObject({ role: "cl_probe_exec" });

    // Nothing that ran left a credential anywhere a reader can reach.
    const body = JSON.stringify(result.json);
    expect(body).not.toContain(RO_PASSWORD);
    expect(body).not.toContain(EXEC_PASSWORD);

    const health = await apiGet(rig, admin, "/v1/dashboard/connections/probe");
    const lastJob = (health.json.connection as { health: { last_job: { type: string; state: string } } }).health.last_job;
    expect(lastJob.type).toBe("test_connection");
    expect(lastJob.state).toBe("succeeded");
  }, 180_000);

  it("a refused credential produces auth_error and the re-auth prompt (gate clause)", async () => {
    // The only change is which reference the connection points at. That
    // is the whole shape of a credential rotation gone wrong, and it is
    // what an operator will actually hit.
    const rebound = await put("/v1/dashboard/connections/probe", {
      connector: { name: "postgres", version_constraint: ">=0.2 <0.3" },
      payload: {
        config: { system: "probe", mode: "live" },
        credentials: [{ key: "dsn", ref: "env://CL_PROBE_WRONG_DSN", required_for: ["live"] }],
      },
    });
    expect(rebound.status).toBe(200);

    const result = await apiPost(rig, admin, "/v1/dashboard/connections/probe/test", {});
    expect(result.status).toBe(200);
    expect(result.json.outcome, JSON.stringify(result.json)).toBe("fail");

    const error = result.json.error as { code: string; message: string; retryable: boolean };
    expect(error.code).toBe("auth_error");
    expect(error.retryable).toBe(false);

    const reauth = result.json.reauth as {
      required: boolean;
      credential_refs: string[];
      action: string;
      message: string;
    };
    expect(reauth.required).toBe(true);
    // The prompt points at the reference, which is all the product
    // holds — J-4's promise, arriving where a person can act on it.
    expect(reauth.credential_refs).toEqual(["env://CL_PROBE_WRONG_DSN"]);
    expect(reauth.action).toContain("env://CL_PROBE_WRONG_DSN");

    // Not one byte of the credential travels with the refusal.
    const body = JSON.stringify(result.json);
    expect(body).not.toContain("not-the-password");
    expect(body).not.toContain(RO_PASSWORD);
    expect(body).not.toContain("cl_probe_ro:");

    // And the connection's health now says red, from the job row.
    const health = await apiGet(rig, admin, "/v1/dashboard/connections/probe");
    const h = (health.json.connection as { health: { status: string; last_job: { error: { code: string } } } }).health;
    expect(h.last_job.error.code).toBe("auth_error");
    expect(h.status).toBe("red");
  }, 180_000);
});
