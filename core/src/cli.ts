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
 * Sync admin (CP-3b, ruling E2 — the stand-in for the Connections UI;
 * direct ops-Postgres access, same trust position as `migrate`):
 *
 *   node dist/cli.js sync systems set FILE
 *       Register/update a connection: {system, connector: {name,
 *       version_constraint?}, payload}. The payload carries credential
 *       *references* only (J-4).
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
import os from "node:os";
import { loadConfig } from "./config.js";
import { createPool } from "./db.js";
import { computeFreshness } from "./freshness.js";
import { defaultMigrationsDir, migrate } from "./migrate.js";
import { readPolicyFromHead } from "./scheduler.js";
import {
  getSyncSystem,
  setHookSecret,
  triggerSystem,
  upsertSyncSystem,
} from "./triggers.js";

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

async function runSync(args: string[]): Promise<number> {
  const [sub, ...rest] = args;

  if (sub === "systems" && rest[0] === "set" && rest[1]) {
    return withPool(async (pool) => {
      const spec = JSON.parse(await readFile(rest[1]!, "utf-8")) as {
        system?: string;
        connector?: { name?: string; version_constraint?: string };
        payload?: Record<string, unknown>;
      };
      if (!spec.system || !spec.connector?.name) {
        console.error("FILE must carry {system, connector: {name}}");
        return 2;
      }
      await upsertSyncSystem(pool, {
        system: spec.system,
        connector_name: spec.connector.name,
        version_constraint: spec.connector.version_constraint ?? "*",
        payload: spec.payload ?? {},
      });
      console.log(`${spec.system}: connection registered (${spec.connector.name})`);
      return 0;
    });
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
    return withPool(async (pool, cfg) => {
      let systems = rest;
      if (systems.length === 0) {
        const { rows } = await pool.query<{ system: string }>(
          `SELECT system FROM sync_systems ORDER BY system`,
        );
        systems = rows.map((r) => r.system);
      }
      if (systems.length === 0) {
        console.error("no connections registered");
        return 1;
      }
      for (const system of systems) {
        const registered = await getSyncSystem(pool, system);
        if (!registered) {
          console.error(`${system}: no such connection`);
          return 1;
        }
        const jobId = await triggerSystem(pool, cfg, registered, {
          kind: "manual",
          detail: { actor: os.userInfo().username, via: "admin-cli" },
        });
        console.log(`${system}: manual trigger recorded (snapshot job ${jobId})`);
      }
      return 0;
    });
  }

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
    return withPool(async (pool) => {
      const { rows } = await pool.query(
        `SELECT run_id, outcome, pr_url, kb_ref, started_at, duration_ms, detail
           FROM runs ORDER BY started_at DESC LIMIT $1`,
        [Number(rest[0] ?? 10) || 10],
      );
      for (const row of rows) {
        console.log(
          `${row.run_id} ${row.outcome}` +
            (row.pr_url ? ` ${row.pr_url}` : "") +
            (row.detail?.stage ? ` [stage ${row.detail.stage}]` : ""),
        );
      }
      return 0;
    });
  }

  console.error(
    "usage: cli.js sync systems set FILE | hook set SYSTEM | now [SYSTEM...] | freshness | runs [N]",
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

  if (!profileName || !kbDir || !publicUrl) {
    console.error("usage: cli.js compile PROFILE --kb DIR --url URL [--out DIR]");
    return 2;
  }

  const { readFile } = await import("node:fs/promises");
  const { existsSync } = await import("node:fs");
  const pathMod = await import("node:path");
  const YAML = (await import("yaml")).default;
  const { compileProfile, writeSetup, listShippedSkills } = await import("./compile.js");

  let file = pathMod.join(kbDir, ".contextlayer", "profiles", `${profileName}.yaml`);
  if (!existsSync(file)) file = pathMod.join(kbDir, ".contextlayer", "profiles", `${profileName}.yml`);
  if (!existsSync(file)) {
    console.error(`no profile "${profileName}" in ${kbDir}/.contextlayer/profiles/`);
    return 1;
  }

  const raw = YAML.parse(await readFile(file, "utf-8")) as Record<string, unknown>;
  const setup = await compileProfile(profileName, raw, { publicUrl });
  const written = await writeSetup(setup, outDir);

  for (const warning of setup.warnings) console.error(`warning: ${warning}`);
  if (setup.warnings.length) {
    console.error(`this release ships: ${(await listShippedSkills()).join(", ") || "(no skills)"}`);
  }
  console.log(`compiled ${setup.displayName} -> ${outDir}`);
  for (const rel of written) console.log(`  ${rel}`);
  return 0;
}

const [, , command, ...rest] = process.argv;
const run =
  command === "migrate" ? runMigrate() :
  command === "enqueue" ? runEnqueue(rest) :
  command === "sync" ? runSync(rest) :
  command === "compile" ? runCompile(rest) :
  Promise.resolve().then(() => {
    console.error("usage: cli.js migrate | enqueue [--wait] FILE... | sync … | compile PROFILE --kb DIR --url URL");
    return 2;
  });

run.then(
  (code) => process.exit(code),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
