/**
 * Ops CLI:
 *
 *   node dist/cli.js migrate
 *       Apply pending migrations (CORE_DATABASE_URL).
 *
 *   node dist/cli.js enqueue [--wait] FILE [FILE ...]
 *       Enqueue one job per JSON file against a running core
 *       (CORE_URL, CORE_TOKEN). Each file is the enqueue request body:
 *       {type, system, connector:{name, version_constraint}, payload:
 *       {config, credentials}, trigger?}. With --wait, polls each job
 *       to a terminal state and exits non-zero unless all succeeded —
 *       the one-command path of the CP-3a exit criterion.
 *
 * Sync admin. **Since A-3 these are clients of the Connections API**
 * (`/v1/dashboard/connections`), not of the database. The direct-DB
 * registry path that stood in for the Connections UI from D-63.8 is
 * deleted, not deprecated: there is exactly one writer of
 * `sync_systems`, the dashboard and this CLI are peers in front of it,
 * and `connections.test.ts` asserts at grep level that no path in this
 * file holds a registry write. Ruling E2 closes here.
 *
 * These commands authenticate as **a person**, not as the platform:
 * `CORE_TOKEN` must be an OIDC access token carrying an ops role (the
 * same identity a browser would sign in with), because a CLI that could
 * do more than its operator is the shadow permission system UI-2
 * forbids — and it is now the same code path either way.
 *
 *   node dist/cli.js sync systems list
 *       Every registered connection with its health.
 *
 *   node dist/cli.js sync systems set FILE
 *       Register/update a connection: {system, connector: {name,
 *       version_constraint?}, payload}. The payload carries credential
 *       *references* only (J-4) — the server refuses material by name.
 *       What is printed back is the row the store held on re-read.
 *
 *   node dist/cli.js sync systems rm SYSTEM
 *       Remove a connection (the store's absence is verified).
 *
 *   node dist/cli.js sync test SYSTEM
 *       Run the connector's builtin probe against the connection.
 *
 *   node dist/cli.js sync hook set SYSTEM
 *       Generate (or rotate) the per-hook shared secret (§4.2). Prints
 *       the secret exactly once; only its sha256 is stored, and the
 *       endpoint reads per request, so rotation needs no restart.
 *
 *   node dist/cli.js sync now [SYSTEM ...]
 *       Manual trigger (§4.3), estate-wide when no system named. A new
 *       DDL handover is `sync systems set` (files as connector config)
 *       followed by `sync now SYSTEM`.
 *
 *   node dist/cli.js sync freshness
 *       §8 computation against sync-policy.yaml at KB HEAD.
 *
 *   node dist/cli.js sync runs [N]
 *       Latest run records.
 */

import { randomBytes, createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { loadConfig } from "./config.js";
import { createPool } from "./db.js";
import { computeFreshness } from "./freshness.js";
import { defaultMigrationsDir, migrate } from "./migrate.js";
import { readPolicyFromHead } from "./scheduler.js";
// Deliberately narrow: `getSyncSystem` is a read and `setHookSecret`
// writes the webhook-secret table. The connection-registry writers are
// not imported here and must not be — that absence is the A-3 gate
// clause, and `connections.test.ts` asserts it over this file's bytes
// (by the writers' names and by their SQL) rather than trusting a
// comment, which is why this one does not spell them out.
import { getSyncSystem, setHookSecret } from "./triggers.js";

const TERMINAL = new Set(["succeeded", "dead_lettered", "cancelled"]);

async function api(
  base: string,
  token: string,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ status: number; json: Record<string, unknown> }> {
  const response = await fetch(`${base}${path}`, {
    method,
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      "x-cl-protocol-version": "1",
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const text = await response.text();
  return { status: response.status, json: text ? JSON.parse(text) : {} };
}

async function runMigrate(): Promise<number> {
  const cfg = loadConfig();
  const pool = createPool(cfg.databaseUrl);
  try {
    const applied = await migrate(pool, defaultMigrationsDir(), (m) => console.log(m));
    console.log(applied.length > 0 ? `applied ${applied.length} migration(s)` : "up to date");
    return 0;
  } finally {
    await pool.end();
  }
}

async function runEnqueue(args: string[]): Promise<number> {
  const wait = args.includes("--wait");
  const files = args.filter((a) => a !== "--wait");
  if (files.length === 0) {
    console.error("usage: cli.js enqueue [--wait] FILE [FILE ...]");
    return 2;
  }
  const base = (process.env.CORE_URL ?? "http://127.0.0.1:8100").replace(/\/$/, "");
  const token = process.env.CORE_TOKEN ?? "";
  if (!token) {
    console.error("CORE_TOKEN is required");
    return 2;
  }

  const jobs: { file: string; jobId: string; system: string }[] = [];
  for (const file of files) {
    const request = JSON.parse(await readFile(file, "utf-8")) as Record<string, unknown>;
    const { status, json } = await api(base, token, "POST", "/v1/jobs", request);
    if (status !== 201 && status !== 200) {
      console.error(`${file}: enqueue failed (${status}): ${JSON.stringify(json)}`);
      return 1;
    }
    console.log(
      `${file}: job ${json.job_id as string}${json.merged ? " (merged into queued job)" : ""}`,
    );
    jobs.push({
      file,
      jobId: json.job_id as string,
      system: (request.system as string) ?? "?",
    });
  }
  if (!wait) return 0;

  let allSucceeded = true;
  for (const job of jobs) {
    for (;;) {
      const { status, json } = await api(base, token, "GET", `/v1/jobs/${job.jobId}`);
      if (status !== 200) {
        console.error(`${job.jobId}: poll failed (${status})`);
        allSucceeded = false;
        break;
      }
      const state = json.state as string;
      if (TERMINAL.has(state)) {
        const meta = (json.result_meta ?? {}) as Record<string, unknown>;
        console.log(
          `${job.system}: ${state}` +
            (state === "succeeded" && meta.snapshot_id
              ? ` — snapshot ${meta.snapshot_id as string} ` +
                `(sha256 ${(meta.sha256 as string | undefined)?.slice(0, 12) ?? "?"}…, ` +
                `${meta.object_count as number} objects)`
              : "") +
            (state === "dead_lettered" ? ` — ${JSON.stringify(json.error)}` : ""),
        );
        if (state !== "succeeded") allSucceeded = false;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
  return allSucceeded ? 0 : 1;
}

async function withPool<T>(fn: (pool: ReturnType<typeof createPool>, cfg: ReturnType<typeof loadConfig>) => Promise<T>): Promise<T> {
  const cfg = loadConfig();
  const pool = createPool(cfg.databaseUrl);
  try {
    return await fn(pool, cfg);
  } finally {
    await pool.end();
  }
}

/** The API base and the operator's own token, for the connection
 * commands. No database credential is involved in any of them. */
function apiContext(): { base: string; token: string } | null {
  const base = (process.env.CORE_URL ?? "http://127.0.0.1:8100").replace(/\/$/, "");
  const token = process.env.CORE_TOKEN ?? "";
  if (!token) {
    console.error(
      "CORE_TOKEN is required: an OIDC access token for an identity holding an ops role.\n" +
        "These commands call the same governed API the dashboard calls, as you — there is no\n" +
        "database path left in this CLI.",
    );
    return null;
  }
  return { base, token };
}

function health(connection: Record<string, unknown>): string {
  const h = (connection.health ?? {}) as { status?: string; reason?: string };
  return `${h.status ?? "?"} — ${h.reason ?? ""}`;
}

async function runSync(args: string[]): Promise<number> {
  const [sub, ...rest] = args;

  if (sub === "systems" && (rest[0] === "list" || rest[0] === undefined)) {
    const ctx = apiContext();
    if (!ctx) return 2;
    const { status, json } = await api(ctx.base, ctx.token, "GET", "/v1/dashboard/connections");
    if (status !== 200) {
      console.error(`connections list failed (${status}): ${JSON.stringify(json)}`);
      return 1;
    }
    const connections = (json.connections ?? []) as Record<string, unknown>[];
    if (connections.length === 0) {
      console.log("no connections registered");
      return 0;
    }
    if (json.policy_readable === false) {
      console.log("(sync-policy.yaml unreadable — freshness reported unknown, not green)\n");
    }
    for (const connection of connections) {
      const connector = (connection.connector ?? {}) as { name?: string };
      console.log(`${connection.system} [${connector.name}] ${health(connection)}`);
    }
    return 0;
  }

  if (sub === "systems" && rest[0] === "set" && rest[1]) {
    const ctx = apiContext();
    if (!ctx) return 2;
    const spec = JSON.parse(await readFile(rest[1]!, "utf-8")) as {
      system?: string;
      connector?: { name?: string; version_constraint?: string };
      payload?: Record<string, unknown>;
    };
    if (!spec.system || !spec.connector?.name) {
      console.error("FILE must carry {system, connector: {name}}");
      return 2;
    }
    const { status, json } = await api(
      ctx.base,
      ctx.token,
      "PUT",
      `/v1/dashboard/connections/${encodeURIComponent(spec.system)}`,
      { connector: spec.connector, payload: spec.payload ?? {} },
    );
    if (status !== 200 && status !== 201) {
      console.error(`${spec.system}: registration refused (${status}) — ${json.error}: ${json.detail}`);
      for (const field of (json.fields ?? []) as string[]) console.error(`  ${field}`);
      return 1;
    }
    // Printed from the response, which the server built from the row it
    // re-read after writing. "registered" is the store's statement here,
    // not this process's (D-84).
    const connection = (json.connection ?? {}) as Record<string, unknown>;
    const connector = (connection.connector ?? {}) as { name?: string };
    console.log(
      `${connection.system}: connection registered (${connector.name}) — read back from the store`,
    );
    console.log(`  health: ${health(connection)}`);
    return 0;
  }

  if (sub === "systems" && rest[0] === "rm" && rest[1]) {
    const ctx = apiContext();
    if (!ctx) return 2;
    const system = rest[1]!;
    const { status, json } = await api(
      ctx.base,
      ctx.token,
      "DELETE",
      `/v1/dashboard/connections/${encodeURIComponent(system)}`,
    );
    if (status === 404) {
      console.error(`${system}: no such connection`);
      return 1;
    }
    if (status !== 200) {
      console.error(`${system}: removal failed (${status}) — ${json.error}: ${json.detail}`);
      return 1;
    }
    console.log(`${system}: connection removed (absence verified in the store)`);
    return 0;
  }

  if (sub === "test" && rest[0]) {
    const ctx = apiContext();
    if (!ctx) return 2;
    const system = rest[0]!;
    const { status, json } = await api(
      ctx.base,
      ctx.token,
      "POST",
      `/v1/dashboard/connections/${encodeURIComponent(system)}/test`,
      {},
    );
    if (status === 404) {
      console.error(`${system}: no such connection`);
      return 1;
    }
    if (status !== 200 && status !== 202) {
      console.error(`${system}: test refused (${status}) — ${json.error}: ${json.detail}`);
      return 1;
    }
    console.log(`${system}: ${json.outcome} (job ${json.job_id})`);
    for (const check of (json.checks ?? []) as Record<string, unknown>[]) {
      const extra = check.message ?? (check.facts ? JSON.stringify(check.facts) : "");
      console.log(`  ${String(check.capability).padEnd(10)} ${check.status}  ${extra}`);
    }
    const unprobed = (json.unprobed ?? []) as string[];
    if (unprobed.length > 0) {
      console.log(`  not exercised: ${unprobed.join(", ")} — unprobed is not a pass`);
    }
    if (json.detail) console.log(`  ${json.detail}`);
    const error = json.error as { code?: string; message?: string } | undefined;
    if (error) console.log(`  ${error.code}: ${error.message}`);
    const reauth = json.reauth as { credential_refs?: string[]; action?: string } | undefined;
    if (reauth) {
      console.log(`  RE-AUTH NEEDED: ${(reauth.credential_refs ?? []).join(", ")}`);
      console.log(`  ${reauth.action}`);
    }
    return json.outcome === "pass" ? 0 : 1;
  }

  if (sub === "hook" && rest[0] === "set" && rest[1]) {
    return withPool(async (pool) => {
      const system = rest[1]!;
      if (!(await getSyncSystem(pool, system))) {
        console.error(`${system}: no such connection — run sync systems set first`);
        return 1;
      }
      const secret = randomBytes(32).toString("hex");
      const hash = createHash("sha256").update(secret).digest("hex");
      const action = await setHookSecret(pool, system, hash);
      console.log(`${system}: hook secret ${action}. POST /v1/hooks/${system}`);
      console.log(`X-CL-Hook-Secret: ${secret}`);
      console.log("(shown once — only its sha256 is stored)");
      return 0;
    });
  }

  if (sub === "now") {
    const ctx = apiContext();
    if (!ctx) return 2;
    let systems = rest;
    if (systems.length === 0) {
      const { status, json } = await api(ctx.base, ctx.token, "GET", "/v1/dashboard/connections");
      if (status !== 200) {
        console.error(`connections list failed (${status}): ${JSON.stringify(json)}`);
        return 1;
      }
      systems = ((json.connections ?? []) as { system: string }[]).map((c) => c.system);
    }
    if (systems.length === 0) {
      console.error("no connections registered");
      return 1;
    }
    for (const system of systems) {
      const { status, json } = await api(
        ctx.base,
        ctx.token,
        "POST",
        `/v1/dashboard/connections/${encodeURIComponent(system)}/sync`,
        {},
      );
      if (status === 404) {
        console.error(`${system}: no such connection`);
        return 1;
      }
      if (status !== 202) {
        console.error(`${system}: trigger refused (${status}) — ${json.error}: ${json.detail}`);
        return 1;
      }
      console.log(`${system}: manual trigger recorded (snapshot job ${json.job_id})`);
    }
    return 0;
  }

  // Freshness stays on the ops database: it is a computation over
  // sync-policy.yaml at KB HEAD and the accepted-snapshot table, with no
  // endpoint of its own yet (that surface is B-1's KB Health). It writes
  // nothing, and in particular it does not touch the connection
  // registry — which is the line A-3 draws.
  if (sub === "freshness") {
    return withPool(async (pool, cfg) => {
      const policy = await readPolicyFromHead(cfg);
      for (const report of await computeFreshness(pool, policy)) {
        const age = report.ageS === null ? "no accepted snapshot" : `${Math.round(report.ageS)}s`;
        console.log(
          `${report.system}: age ${age} / threshold ${report.thresholdS}s ` +
            `[${report.mode}] ${report.warning ? "WARNING — " + report.guidance : "ok"}`,
        );
      }
      return 0;
    });
  }

  if (sub === "runs") {
    const ctx = apiContext();
    if (!ctx) return 2;
    const { status, json } = await api(
      ctx.base,
      ctx.token,
      "GET",
      `/v1/runs?limit=${Number(rest[0] ?? 10) || 10}`,
    );
    if (status !== 200) {
      console.error(`runs read failed (${status}): ${JSON.stringify(json)}`);
      return 1;
    }
    for (const row of (json.runs ?? []) as Record<string, any>[]) {
      console.log(
        `${row.run_id} ${row.outcome}` +
          (row.pr_url ? ` ${row.pr_url}` : "") +
          (row.detail?.stage ? ` [stage ${row.detail.stage}]` : ""),
      );
    }
    return 0;
  }

  console.error(
    "usage: cli.js sync systems list | systems set FILE | systems rm SYSTEM | test SYSTEM | " +
      "hook set SYSTEM | now [SYSTEM...] | freshness | runs [N]",
  );
  return 2;
}

/**
 * `compile PROFILE --kb DIR --url URL [--out DIR]` — platform-architecture
 * §5's one-line Claude Code setup. The profile is read from the KB clone
 * (customer-owned); the skills bundle comes from the core image and never
 * from the KB (D-75.1). Needs no database: compilation is a pure function
 * of the profile YAML plus this release's skills.
 */
async function runCompile(args: string[]): Promise<number> {
  const positional = args.filter((a) => !a.startsWith("--"));
  const flag = (name: string): string | undefined => {
    const i = args.indexOf(`--${name}`);
    return i >= 0 ? args[i + 1] : undefined;
  };
  const profileName = positional[0];
  const kbDir = flag("kb");
  const publicUrl = flag("url");
  const outDir = flag("out") ?? `./contextlayer-${profileName ?? "profile"}`;
  // D-116.7: the KB address the document-writing skills clone. Defaults
  // to the sync remote this core is configured with, because that is the
  // KB it serves; a compile run outside a configured core can pass it.
  const kbRemote = flag("kb-remote") ?? process.env.SYNC_GIT_REMOTE ?? null;

  if (!profileName || !kbDir || !publicUrl) {
    console.error("usage: cli.js compile PROFILE --kb DIR --url URL [--out DIR] [--kb-remote URL]");
    return 2;
  }

  const { readFile } = await import("node:fs/promises");
  const { existsSync } = await import("node:fs");
  const pathMod = await import("node:path");
  const YAML = (await import("yaml")).default;
  const { compileProfile, writeSetup, MissingSkillError } = await import("./compile.js");

  let file = pathMod.join(kbDir, ".contextlayer", "profiles", `${profileName}.yaml`);
  if (!existsSync(file)) file = pathMod.join(kbDir, ".contextlayer", "profiles", `${profileName}.yml`);
  if (!existsSync(file)) {
    console.error(`no profile "${profileName}" in ${kbDir}/.contextlayer/profiles/`);
    return 1;
  }

  const raw = YAML.parse(await readFile(file, "utf-8")) as Record<string, unknown>;
  let setup;
  try {
    setup = await compileProfile(profileName, raw, { publicUrl, kbRemote });
  } catch (err) {
    // F-7: a missing skill fails the compile and writes nothing. Report
    // it as an operator-actionable error, not a stack trace.
    if (err instanceof MissingSkillError) {
      console.error(`compile failed: ${err.message}`);
      return 1;
    }
    throw err;
  }
  const written = await writeSetup(setup, outDir);

  for (const warning of setup.warnings) console.error(`warning: ${warning}`);
  console.log(`compiled ${setup.displayName} -> ${outDir}`);
  for (const rel of written) console.log(`  ${rel}`);
  return 0;
}

/**
 * `publish deliveries` — the MCP §6.8 amendment's ops surface: every
 * model delivery per (artifact, target), with revisions that never
 * reached `attest` marked DANGLING, loudly. A delivered-but-unattested
 * revision means the two-call contract stopped between calls — the
 * model changed but no verified report was recorded against it.
 */
async function runPublish(args: string[]): Promise<number> {
  if (args[0] !== "deliveries") {
    console.error("usage: cli.js publish deliveries");
    return 2;
  }
  const cfg = loadConfig();
  const pool = createPool(cfg.databaseUrl);
  try {
    const { rows } = await pool.query(
      `SELECT d.artifact_id, d.target, d.revision, d.dataset_id, d.delivered_at,
              a.report_id, a.definition_hash, a.attested_at
         FROM model_deliveries d
         LEFT JOIN report_attestations a
           ON a.artifact_id = d.artifact_id AND a.target = d.target
          AND a.revision = d.revision
        ORDER BY d.delivered_at DESC`,
    );
    if (rows.length === 0) {
      console.log("no model deliveries recorded");
      return 0;
    }
    let dangling = 0;
    for (const row of rows) {
      const attested = row.report_id
        ? `attested report=${row.report_id} at ${row.attested_at.toISOString()}`
        : "DANGLING — delivered but never attested (no verified report records this revision)";
      if (!row.report_id) dangling += 1;
      console.log(
        `${row.artifact_id} rev ${row.revision} → ${row.target} dataset=${row.dataset_id} ` +
          `delivered ${row.delivered_at.toISOString()} | ${attested}`,
      );
    }
    if (dangling > 0) {
      console.log(`\n${dangling} dangling deliver${dangling === 1 ? "y" : "ies"} — ` +
        "finish the authoring flow (author → deploy → verify → attest) or re-deliver.");
    }
    return dangling > 0 ? 1 : 0;
  } finally {
    await pool.end();
  }
}

const [, , command, ...rest] = process.argv;
const run =
  command === "migrate" ? runMigrate() :
  command === "enqueue" ? runEnqueue(rest) :
  command === "sync" ? runSync(rest) :
  command === "compile" ? runCompile(rest) :
  command === "publish" ? runPublish(rest) :
  Promise.resolve().then(() => {
    console.error("usage: cli.js migrate | enqueue [--wait] FILE... | sync … | compile PROFILE --kb DIR --url URL | publish deliveries");
    return 2;
  });

run.then(
  (code) => process.exit(code),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
