/**
 * A-3 (Connections are operable) and B-2 (the module that faces it).
 *
 * The gate's five clauses, each with the negative that proves it:
 *
 * 1. CRUD + test over the governed API, role-checked **server-side** —
 *    a reporter's call is a 403 from the server, not an absent button.
 * 2. Per-source health, read from stores that already exist.
 * 3. An `auth_error` produces a re-auth prompt.
 * 4. The admin CLI is a client of the same API; no direct-DB registry
 *    path remains (asserted over `cli.ts`'s bytes).
 * 5. The D-84 silent-failure shape is structurally impossible —
 *    registration returns what the store holds. Proved the only way it
 *    can be: by making the write silently not happen and watching the
 *    API refuse to report success.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  apiGet,
  apiPost,
  login,
  setupDashboardRig,
  type BrowserSession,
  type DashboardRig,
} from "./dashboard-helpers.js";
import { FEATURE_TOGGLES } from "../src/config.js";
import { healthFor, readConnectionSpec, PayloadRejected } from "../src/connections.js";
import { modulesFor } from "../src/spa.js";
import { getSyncSystem, upsertSyncSystem, RegistryWriteNotObserved } from "../src/triggers.js";
import type { KbState } from "../src/kbread.js";
import type { SyncPolicy } from "../src/policy.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CORE_DIR = path.resolve(HERE, "..");

/** PUT/DELETE as a cookie session — the shapes the module itself uses. */
async function apiSend(
  rig: DashboardRig,
  session: BrowserSession,
  method: "PUT" | "DELETE",
  path_: string,
  body?: unknown,
): Promise<{ status: number; json: Record<string, unknown> }> {
  const response = await fetch(`${rig.base}${path_}`, {
    method,
    headers: {
      cookie: session.cookie,
      "x-cl-csrf": session.csrf,
      ...(body !== undefined ? { "content-type": "application/json" } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const text = await response.text();
  return { status: response.status, json: text ? JSON.parse(text) : {} };
}

const DRILL_SPEC = {
  connector: { name: "postgres", version_constraint: ">=0.2 <0.3" },
  payload: {
    config: { system: "wired", mode: "live", dsn_env: "CL_WIRED_DSN" },
    credentials: [{ key: "dsn", ref: "env://CL_WIRED_DSN", required_for: ["live"] }],
  },
};

describe("A-3 connections API", () => {
  let rig: DashboardRig;
  /** ops + steward roles — the platform admin (playbook R3). */
  let admin: BrowserSession;
  /** steward profile, no ops role — reads and does not write. */
  let reader: BrowserSession;
  /** reporter — sees nothing here at all. */
  let reporter: BrowserSession;

  beforeAll(async () => {
    rig = await setupDashboardRig();
    admin = await login(rig, "steward");
    reader = await login(rig, "auditlite");
    reporter = await login(rig, "reporter");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  // -- (1) role checks, server-side ------------------------------------------

  it("gates by role on the server: ops writes, steward reads, reporter is refused", async () => {
    expect(rig.core.cfg.dashboard.adminRoles).toContain("ops");
    expect(admin.roles).toContain("ops");
    expect(reader.roles).not.toContain("ops");

    const write = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/wired", DRILL_SPEC);
    expect(write.status).toBe(201);

    // The steward reads — and the response says, from the server, that
    // this identity's scope is read.
    const read = await apiGet(rig, reader, "/v1/dashboard/connections");
    expect(read.status).toBe(200);
    expect(read.json.role_scope).toBe("read");
    expect((read.json.connections as unknown[]).length).toBeGreaterThan(0);

    // …and cannot write, test, or delete. Each refusal is the server's.
    const stewardWrite = await apiSend(rig, reader, "PUT", "/v1/dashboard/connections/wired", DRILL_SPEC);
    expect(stewardWrite.status).toBe(403);
    expect(stewardWrite.json.error).toBe("forbidden");
    const stewardTest = await apiPost(rig, reader, "/v1/dashboard/connections/wired/test", {});
    expect(stewardTest.status).toBe(403);
    const stewardDelete = await apiSend(rig, reader, "DELETE", "/v1/dashboard/connections/wired");
    expect(stewardDelete.status).toBe(403);

    // The reporter cannot even list: DT-1's shape on this endpoint.
    const reporterList = await apiGet(rig, reporter, "/v1/dashboard/connections");
    expect(reporterList.status).toBe(403);
    const reporterOne = await apiGet(rig, reporter, "/v1/dashboard/connections/wired");
    expect(reporterOne.status).toBe(403);
    const reporterWrite = await apiSend(rig, reporter, "PUT", "/v1/dashboard/connections/x", DRILL_SPEC);
    expect(reporterWrite.status).toBe(403);

    // The row survives every refusal — a 403 changed nothing.
    expect(await getSyncSystem(rig.core.pool, "wired")).not.toBeNull();
  });

  it("requires a session at all, and a CSRF token on cookie writes", async () => {
    const anonymous = await fetch(`${rig.base}/v1/dashboard/connections`);
    expect(anonymous.status).toBe(401);
    const noCsrf = await fetch(`${rig.base}/v1/dashboard/connections/wired`, {
      method: "PUT",
      headers: { cookie: admin.cookie, "content-type": "application/json" },
      body: JSON.stringify(DRILL_SPEC),
    });
    expect(noCsrf.status).toBe(403);
    expect((await noCsrf.json()).error).toBe("csrf_required");
  });

  // -- (2) references only ---------------------------------------------------

  it("refuses credential material by name, and never echoes the value", async () => {
    const secret = "postgres://someone:hunter2@db.internal:5432/app";
    const inline = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/leaky", {
      connector: { name: "postgres" },
      payload: { config: { system: "leaky", mode: "live", dsn: secret }, credentials: [] },
    });
    expect(inline.status).toBe(400);
    expect(inline.json.error).toBe("raw_secret_rejected");
    expect((inline.json.fields as string[]).join(" ")).toContain("dsn_env");
    // The refusal is quotable: no part of it carries the secret.
    expect(JSON.stringify(inline.json)).not.toContain("hunter2");
    expect(JSON.stringify(inline.json)).not.toContain(secret);

    // A credential entry holding a value rather than a reference.
    const valued = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/leaky", {
      connector: { name: "postgres" },
      payload: {
        config: { system: "leaky", mode: "live", dsn_env: "X" },
        credentials: [{ key: "dsn", ref: secret }],
      },
    });
    expect(valued.status).toBe(400);
    expect(valued.json.error).toBe("raw_secret_rejected");
    expect(JSON.stringify(valued.json)).not.toContain("hunter2");

    // A service-account key pasted into a config field it was not
    // named for — caught by shape, not by field name.
    const pasted = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/leaky", {
      connector: { name: "ga4" },
      payload: {
        config: { system: "leaky", mode: "api", property_id: "1", note: '{"private_key": "-----BEGIN PRIVATE KEY-----"}' },
        credentials: [],
      },
    });
    expect(pasted.status).toBe(400);
    expect(pasted.json.error).toBe("raw_secret_rejected");

    // Nothing was stored by any of the three.
    expect(await getSyncSystem(rig.core.pool, "leaky")).toBeNull();

    // vault:// is accepted now so A-4 changes the resolver, not this.
    const vaulted = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/vaulted", {
      connector: { name: "postgres" },
      payload: {
        config: { system: "vaulted", mode: "live", dsn_env: "CL_VAULTED_DSN" },
        credentials: [{ key: "dsn", ref: "vault://kv/data/pilot#dsn", required_for: ["live"] }],
      },
    });
    expect(vaulted.status).toBe(201);
    await apiSend(rig, admin, "DELETE", "/v1/dashboard/connections/vaulted");
  });

  it("rejects material on the parse path too, so no caller can skip the gate", () => {
    expect(() =>
      readConnectionSpec("s", {
        connector: { name: "postgres" },
        payload: { config: { system: "s", client_secret: "abc" }, credentials: [] },
      }),
    ).toThrow(PayloadRejected);
    expect(() =>
      readConnectionSpec("s", {
        connector: { name: "postgres" },
        payload: { config: { system: "s" }, credentials: [{ key: "dsn", ref: "env://OK", value: "x" }] },
      }),
    ).toThrow(PayloadRejected);
    // The permitted shape stays permitted.
    const ok = readConnectionSpec("s", {
      connector: { name: "postgres" },
      payload: { config: { system: "s", dsn_env: "OK" }, credentials: [{ key: "dsn", ref: "env://OK" }] },
    });
    expect(ok.payload.credentials[0]!.ref).toBe("env://OK");
  });

  // -- (5) the D-84 shape, structurally --------------------------------------

  it("registration returns what the store holds — the response is the read-back", async () => {
    const put = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/wired", {
      ...DRILL_SPEC,
      payload: {
        ...DRILL_SPEC.payload,
        config: { ...DRILL_SPEC.payload.config, schemas: ["shop"] },
      },
    });
    expect(put.status).toBe(200); // existed already → update
    expect(put.json.read_back).toBe(true);
    const returned = put.json.connection as { config: Record<string, unknown> };

    const fetched = await apiGet(rig, admin, "/v1/dashboard/connections/wired");
    expect((fetched.json.connection as typeof returned).config).toEqual(returned.config);
    const stored = await getSyncSystem(rig.core.pool, "wired");
    expect((stored!.payload as { config: unknown }).config).toEqual(returned.config);
  });

  it("a write the store does not take cannot be reported as success (D-84)", async () => {
    // The exact shape that cost two silent days: the write reports no
    // error and the row is not there. Reproduced by making the store
    // swallow it — a BEFORE trigger returning NULL — because a gate
    // clause about silent failure is worth only as much as the silent
    // failure it was tested against.
    await rig.core.pool.query(`
      CREATE OR REPLACE FUNCTION cl_test_swallow() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$`);
    await rig.core.pool.query(`
      CREATE TRIGGER cl_test_swallow_writes BEFORE INSERT OR UPDATE ON sync_systems
      FOR EACH ROW EXECUTE FUNCTION cl_test_swallow()`);
    try {
      const swallowed = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/ghost", {
        connector: { name: "postgres" },
        payload: { config: { system: "ghost", mode: "live", dsn_env: "X" }, credentials: [] },
      });
      expect(swallowed.status).toBe(500);
      expect(swallowed.json.error).toBe("write_not_observed");
      expect(await getSyncSystem(rig.core.pool, "ghost")).toBeNull();

      // An *update* silently ignored is the same refusal: the row read
      // back is not the row that was written.
      const stale = await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/wired", {
        connector: { name: "postgres", version_constraint: "*" },
        payload: { config: { system: "wired", mode: "ddl-file", ddl_files: ["x.sql"], image: "postgres:16" }, credentials: [] },
      });
      expect(stale.status).toBe(500);
      expect(stale.json.error).toBe("write_not_observed");

      // …and the guarantee lives in the registry, not the handler, so
      // every writer in the codebase inherits it — tests included.
      await expect(
        upsertSyncSystem(rig.core.pool, {
          system: "ghost",
          connector_name: "postgres",
          version_constraint: "*",
          payload: {},
        }),
      ).rejects.toBeInstanceOf(RegistryWriteNotObserved);
    } finally {
      await rig.core.pool.query(`DROP TRIGGER cl_test_swallow_writes ON sync_systems`);
      await rig.core.pool.query(`DROP FUNCTION cl_test_swallow()`);
    }
  });

  it("deletion proves the absence and 404s when there was nothing to remove", async () => {
    await apiSend(rig, admin, "PUT", "/v1/dashboard/connections/scratch", {
      connector: { name: "postgres" },
      payload: { config: { system: "scratch", mode: "live", dsn_env: "X" }, credentials: [] },
    });
    const removed = await apiSend(rig, admin, "DELETE", "/v1/dashboard/connections/scratch");
    expect(removed.status).toBe(200);
    expect(removed.json.read_back).toBe(true);
    expect(await getSyncSystem(rig.core.pool, "scratch")).toBeNull();
    const again = await apiSend(rig, admin, "DELETE", "/v1/dashboard/connections/scratch");
    expect(again.status).toBe(404);
  });

  // -- (2) health ------------------------------------------------------------

  it("reports per-source health from what already exists, and says 'unknown' rather than green", async () => {
    const list = await apiGet(rig, admin, "/v1/dashboard/connections");
    const wired = (list.json.connections as { system: string; health: { status: string; reason: string } }[]).find(
      (c) => c.system === "wired",
    )!;
    // No snapshot has ever been accepted for this scratch system, so
    // the honest answer is amber with the reason spelled out — never a
    // green tick for a source nobody has ever read.
    expect(wired.health.status).toBe("amber");
    expect(wired.health.reason).toMatch(/no snapshot|no job has run/);

    // The drill system has a real accepted snapshot behind it.
    const direct = await healthFor(rig.core.pool, "drill", null);
    expect(direct.freshness).toBe("unknown");
    expect(direct.status).toBe("unknown");
    expect(direct.reason).toContain("sync-policy.yaml");
    expect(direct.snapshot).not.toBeNull();
    expect(direct.snapshot!.object_count).toBeGreaterThan(0);

    // With a policy in hand the same rows produce a verdict.
    const policy = {
      systems: new Map([
        ["drill", { system: "drill", freshnessThresholdS: 86400, scheduleIntervalS: null, webhook: false, manual: true }],
      ]),
      acquisitionBudgetS: null,
    };
    const judged = await healthFor(rig.core.pool, "drill", policy);
    expect(["green", "red"]).toContain(judged.status);
    expect(judged.policy!.threshold_s).toBe(86400);

    // A threshold of zero makes any snapshot stale — the red path.
    const strict = {
      systems: new Map([
        ["drill", { system: "drill", freshnessThresholdS: 0, scheduleIntervalS: null, webhook: false, manual: true }],
      ]),
      acquisitionBudgetS: null,
    };
    expect((await healthFor(rig.core.pool, "drill", strict)).status).toBe("red");

    // A connection the policy does not list is not a sync source, and
    // must not sit amber forever for failing to be one: a publish
    // target never produces a snapshot, so its last job is its verdict.
    // Getting this wrong makes the playbook's "health green" exit
    // unreachable for Looker Studio and Power BI on the real pilot.
    const publisherOnly = { systems: new Map(), acquisitionBudgetS: null } as SyncPolicy;
    const drillAsTarget = await healthFor(rig.core.pool, "drill", publisherOnly);
    expect(drillAsTarget.freshness).toBe("not_a_sync_source");
    expect(drillAsTarget.status).toBe("green");
    expect(drillAsTarget.reason).toContain("not a sync source");

    // …and one with no job at all is amber, saying which of the two
    // things is true: not expected to snapshot, and never exercised.
    const untouched = await healthFor(rig.core.pool, "never-used", publisherOnly);
    expect(untouched.status).toBe("amber");
    expect(untouched.reason).toContain("no job has run for it yet");
  });

  // -- (1)/(3) test-connection ------------------------------------------------

  it("test-connection runs as a job and reports honestly when no runner answers", async () => {
    // No runner is hosting connectors in this rig, so the probe cannot
    // return a verdict. The endpoint says exactly that — `pending`, with
    // the job id — rather than reporting a failure of the source.
    const result = await apiPost(rig, admin, "/v1/dashboard/connections/wired/test", {});
    expect([200, 202]).toContain(result.status);
    expect(result.json.outcome).toBe("pending");
    expect(typeof result.json.job_id).toBe("string");
    expect(String(result.json.detail)).toContain("no runner");

    // The job really is a `test_connection` job for this system,
    // carrying the registration's own references and nothing else.
    const { rows } = await rig.core.pool.query<{ type: string; payload: { credentials?: unknown[] } }>(
      `SELECT type, payload FROM jobs WHERE job_id = $1`,
      [result.json.job_id as string],
    );
    expect(rows[0]!.type).toBe("test_connection");
    expect(rows[0]!.payload.credentials).toEqual([
      { key: "dsn", ref: "env://CL_WIRED_DSN", required_for: ["live"] },
    ]);
    expect(JSON.stringify(rows[0]!.payload)).not.toContain("hunter2");
  }, 90_000);

  it("an auth_error becomes a re-auth prompt naming references, never values", async () => {
    // Drive the failure the way a runner would: the probe job fails with
    // the taxonomy's `auth_error`, which is what a refused credential
    // produces at every connector (connectors/sdk/errors.py).
    const started = await apiPost(rig, admin, "/v1/dashboard/connections/wired/test", {});
    const jobId = started.json.job_id as string;
    await rig.core.pool.query(
      `UPDATE jobs SET state = 'dead_lettered', error = $2::jsonb, finished_at = now() WHERE job_id = $1`,
      [
        jobId,
        JSON.stringify({
          code: "auth_error",
          message: "postgres authentication failed (check the read-only role credentials)",
          retryable: false,
          detail: { checks: [{ capability: "metadata", status: "fail" }] },
        }),
      ],
    );
    await rig.core.pool.query(`SELECT pg_notify('job_done', $1)`, [jobId]);

    const second = await apiPost(rig, admin, "/v1/dashboard/connections/wired/test", {});
    // The second call enqueues its own job; drive that one to the same
    // terminal state so the response under test is deterministic.
    const secondId = second.json.job_id as string;
    if (second.json.outcome === "pending") {
      await rig.core.pool.query(
        `UPDATE jobs SET state = 'dead_lettered', error = $2::jsonb, finished_at = now() WHERE job_id = $1`,
        [secondId, JSON.stringify({ code: "auth_error", message: "credential refused", retryable: false })],
      );
    }

    const final = await apiGet(rig, admin, `/v1/dashboard/connections/wired`);
    const health = (final.json.connection as { health: { status: string; last_job: { error: { code: string } } } }).health;
    expect(health.last_job.error.code).toBe("auth_error");
    expect(health.status).toBe("red");
  }, 180_000);

  // -- (4) the CLI holds no registry write ------------------------------------

  it("no CLI path writes the connection registry (E2 closed, not stood in for)", () => {
    const cli = readFileSync(path.join(CORE_DIR, "src", "cli.ts"), "utf-8");
    // The registry writers, by name and by SQL. Any of these appearing
    // in the CLI means the direct-DB path grew back.
    for (const forbidden of [
      "upsertSyncSystem",
      "deleteSyncSystem",
      "INSERT INTO sync_systems",
      "UPDATE sync_systems",
      "DELETE FROM sync_systems",
    ]) {
      expect(cli).not.toContain(forbidden);
    }
    // And it does reach the API instead.
    expect(cli).toContain("/v1/dashboard/connections/");
  });
});

// ---------------------------------------------------------------------------

describe("B-2 dashboard shell", () => {
  let rig: DashboardRig;
  let admin: BrowserSession;
  let reporter: BrowserSession;

  beforeAll(async () => {
    // The bundle is an artifact of a build step, so build it: a test
    // that asserts over a stale bundle asserts nothing.
    execFileSync("node", [path.join(CORE_DIR, "web", "build.mjs")], { cwd: CORE_DIR, stdio: "pipe" });
    rig = await setupDashboardRig();
    admin = await login(rig, "steward");
    reporter = await login(rig, "reporter");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  it("/healthz states whether the dashboard is on at all (D-84.2's lesson)", async () => {
    // A core started without the MCP env registers no dashboard route
    // and answers 404 everywhere, while /healthz still says `ok`. That
    // is indistinguishable from a broken build from the outside — and it
    // is exactly what happened on the pilot the first time this runbook
    // was followed. The packet has to say it.
    const probe = await fetch(`${rig.base}/healthz`);
    const body = (await probe.json()) as { instance: Record<string, unknown> };
    expect(body.instance.dashboard_enabled).toBe(true);

    // D-110.2 widened this from three hand-picked fields to the whole
    // toggle set. Asserting against FEATURE_TOGGLES rather than a literal
    // list is the point: a toggle added to the core without a line in the
    // health packet fails here, so no future surface can be silently off
    // *and* unreportable — which is the pair that cost the two days.
    for (const { flag } of FEATURE_TOGGLES) {
      expect(body.instance).toHaveProperty(flag);
      expect(typeof body.instance[flag]).toBe("boolean");
    }
  });

  it("serves the SPA as static assets from the core, behind no second server", async () => {
    const shell = await fetch(`${rig.base}/app/`);
    expect(shell.status).toBe(200);
    expect(shell.headers.get("content-type")).toContain("text/html");
    const html = await shell.text();
    expect(html).toContain('id="root"');

    const js = await fetch(`${rig.base}/app/app.js`);
    expect(js.status).toBe(200);
    expect(js.headers.get("content-type")).toContain("javascript");

    // The bare address lands somewhere rather than 401ing at a person.
    const root = await fetch(`${rig.base}/`, { redirect: "manual" });
    expect(root.status).toBe(302);
    expect(root.headers.get("location")).toBe("/app/");
  });

  it("DT-2: the bundle contains no role-conditional logic", () => {
    const bundle = readFileSync(path.join(CORE_DIR, "web", "dist", "app.js"), "utf-8");
    // Over the *shipped bundle*, because that is what a browser runs:
    // a role name anywhere in it would mean the client knows the role
    // model, which is the first step to deciding with it.
    for (const role of ['"steward"', '"reporter"', '"ops"', '"auditor"', '"benchmark"']) {
      expect(bundle).not.toContain(role);
    }
    for (const shape of ["roles.includes", "roles.some", "hasRole", "isAdmin", "isSteward"]) {
      expect(bundle).not.toContain(shape);
    }

    // Over the *app's own sources*, because React itself legitimately
    // contains the escape hatches and a bundle-wide grep would only
    // ever be measuring React. What matters is that no screen we wrote
    // reaches for them (UI-5's injection surface, D-103's persistence).
    const sources = ["main.tsx", "App.tsx", "Connections.tsx", "ui.tsx", "api.ts"]
      .map((f) => readFileSync(path.join(CORE_DIR, "web", "src", f), "utf-8"))
      .join("\n");
    for (const forbidden of [
      "dangerouslySetInnerHTML",
      "innerHTML",
      "localStorage",
      "sessionStorage",
      "indexedDB",
      "document.cookie",
    ]) {
      expect(sources).not.toContain(forbidden);
    }
    // …and no password-shaped input exists to type a secret into.
    expect(sources).not.toContain('type="password"');
  });

  it("the module map is the server's answer, resolved from dashboard.yaml", async () => {
    const mine = await apiGet(rig, admin, "/v1/dashboard/modules");
    expect(mine.status).toBe(200);
    const modules = mine.json.modules as { id: string; built: boolean }[];
    expect(modules.find((m) => m.id === "connections")!.built).toBe(true);
    // The unbuilt ones are declared and marked, not hidden: a menu that
    // silently omits a module teaches nobody it is coming (UI-10).
    expect(modules.some((m) => !m.built)).toBe(true);
    // This KB carries no dashboard.yaml, and the answer says which
    // configuration produced the list rather than implying one.
    expect(mine.json.config_source).toBe("default");

    // Every authenticated identity gets a map; what they can *do* is
    // the module API's answer, not this one's.
    const theirs = await apiGet(rig, reporter, "/v1/dashboard/modules");
    expect(theirs.status).toBe(200);

    const anonymous = await fetch(`${rig.base}/v1/dashboard/modules`);
    expect(anonymous.status).toBe(401);
  });

  it("dashboard.yaml selects modules and role views, server-side", () => {
    const ws = {
      dashboard: {
        branding: { name: "Acme Context Layer" },
        modules: { connections: { enabled: true }, audit: { enabled: false } },
        role_views: { "data-team": ["connections"], sales: ["profiles"] },
      },
    } as unknown as KbState;

    const dataTeam = modulesFor(ws, ["data-team"]);
    expect(dataTeam.source).toBe("kb");
    expect(dataTeam.branding).toBe("Acme Context Layer");
    expect(dataTeam.modules.map((m) => m.id)).toEqual(["connections"]);

    // A disabled module is not reachable even for a role that names it.
    expect(modulesFor(ws, ["data-team", "sales"]).modules.map((m) => m.id)).toEqual([
      "connections",
      "profiles",
    ]);

    // A role the file says nothing about sees nothing — the narrow
    // reading, so a half-applied config never looks fully applied.
    expect(modulesFor(ws, ["nobody"]).modules).toEqual([]);

    // No dashboard.yaml at all: the shipped default, named as such.
    const bare = modulesFor({} as KbState, ["data-team"]);
    expect(bare.source).toBe("default");
    expect(bare.modules.length).toBeGreaterThan(1);
  });
});
