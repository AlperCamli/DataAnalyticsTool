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
 */

import { readFile } from "node:fs/promises";
import { loadConfig } from "./config.js";
import { createPool } from "./db.js";
import { defaultMigrationsDir, migrate } from "./migrate.js";

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

const [, , command, ...rest] = process.argv;
const run =
  command === "migrate" ? runMigrate() :
  command === "enqueue" ? runEnqueue(rest) :
  Promise.resolve().then(() => {
    console.error("usage: cli.js migrate | enqueue [--wait] FILE...");
    return 2;
  });

run.then(
  (code) => process.exit(code),
  (err) => {
    console.error(err);
    process.exit(1);
  },
);
