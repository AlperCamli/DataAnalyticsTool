/**
 * Per-file test rig: every startCore() call provisions a fresh database
 * on the shared server, migrates it, and boots a real listening core
 * with fast-test timing defaults. The delivery gate runs the actual
 * Python wrapper (repo venv locally, `python` in CI via
 * CORE_TEST_PYTHON), so J-6 in tests is the real J-6.
 */

import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

// `inject` reads the admin DB URL that vitest's global-setup provides.
// It is imported lazily (top-level await, gated on the standalone escape
// hatch below) because importing `vitest` at module scope crashes
// vite-node — and the standalone fixture-deployment launcher (D-78 layer
// (b)) runs this module *outside* vitest. That launcher always supplies
// CORE_TEST_DATABASE_URL, so it never needs `inject` and never loads it.
let injectFn: ((key: string) => string) | null = null;
if (!process.env.CORE_TEST_DATABASE_URL) {
  ({ inject: injectFn } = await import("vitest"));
}
import type { CoreConfig } from "../src/config.js";
import { createPool, JobsNotifier } from "../src/db.js";
import { migrate } from "../src/migrate.js";
import { buildServer } from "../src/server.js";

export const TEST_TOKEN = "test-token";
/** P-A (D-66.1): the ops/read surface takes a distinct service-token set. */
export const TEST_OPS_TOKEN = "test-ops-token";

export function repoRoot(): string {
  return path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
}

export function pythonPath(): string {
  if (process.env.CORE_TEST_PYTHON) return process.env.CORE_TEST_PYTHON;
  const venv = path.join(repoRoot(), ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export function adminUrl(): string {
  if (process.env.CORE_TEST_DATABASE_URL) return process.env.CORE_TEST_DATABASE_URL;
  if (!injectFn) throw new Error("adminUrl: no CORE_TEST_DATABASE_URL and vitest inject unavailable");
  return injectFn("adminUrl");
}

function withDatabase(url: string, database: string): string {
  const parsed = new URL(url);
  parsed.pathname = `/${database}`;
  return parsed.toString();
}

export async function createTestDb(): Promise<{ url: string; drop: () => Promise<void> }> {
  const name = `cl_test_${randomBytes(6).toString("hex")}`;
  const admin = new pg.Client({ connectionString: adminUrl() });
  await admin.connect();
  await admin.query(`CREATE DATABASE ${name}`);
  await admin.end();
  return {
    url: withDatabase(adminUrl(), name),
    drop: async () => {
      const client = new pg.Client({ connectionString: adminUrl() });
      await client.connect();
      await client.query(`DROP DATABASE IF EXISTS ${name} WITH (FORCE)`).catch(() => {});
      await client.end();
    },
  };
}

export interface TestCore {
  cfg: CoreConfig;
  pool: pg.Pool;
  baseUrl: string;
  logs: () => string;
  stop: () => Promise<void>;
}

export async function startCore(overrides: Partial<CoreConfig> = {}): Promise<TestCore> {
  const { url, drop } = await createTestDb();
  const pool = createPool(url);
  await migrate(pool, path.resolve(repoRoot(), "core", "migrations"));
  const cfg: CoreConfig = {
    databaseUrl: url,
    host: "127.0.0.1",
    port: 0,
    runnerTokens: new Map<string, string | null>([
      [TEST_TOKEN, null],
      ["bound-token", "runner-bound"],
    ]),
    opsTokens: new Map<string, string | null>([[TEST_OPS_TOKEN, "test-ops"]]),
    opsRoles: ["ops", "steward"],
    validatorCmd: [pythonPath(), "-m", "snapshot.accept"],
    migrateOnStart: false,
    logLevel: "info",
    leaseTtlS: 60,
    retryBaseS: 0, // immediate requeue: tests assert states, not delays
    retryCapS: 1,
    maxDeferrals: 20,
    resultMaxBytes: 64 * 1024 * 1024,
    snapshotRetention: 10,
    sweepIntervalMs: 60_000, // tests sweep explicitly unless overridden
    claimPollMs: 50,
    sync: {
      enabled: false,
      gitRemote: "",
      gitToken: "",
      gitProvider: "local",
      gitApiBase: "https://api.github.invalid",
      baseBranch: "main",
      committerName: "contextlayer-sync",
      committerEmail: "sync@contextlayer.invalid",
      pythonCmd: [pythonPath()],
      workdir: "/tmp/cl-sync-test",
      tickS: 3600,
      acquisitionBudgetS: 60,
      acquirePollMs: 100,
      prRetries: 3,
      prRetryBaseMs: 50,
      hookBodyMaxBytes: 64 * 1024,
      wheelPath: null,
      wheelVersion: null,
      platformCommit: null,
      wheelBuilt: null,
    },
    mcp: {
      enabled: false,
      publicUrl: "http://127.0.0.1:0",
      oidcIssuer: "",
      oidcClientId: "",
      oidcClientSecret: "",
      rolesClaim: "roles",
      kbRefreshMs: 0, // tests read HEAD every call (the §3 ideal)
      vtokenTtlS: 300,
      limits: {
        readPerMin: 1000,
        validatePerMin: 1000,
        executePerMin: 1000,
        publishPerHour: 1000,
        flagPerSession: 1000,
      },
      ledgerRetentionDays: 90,
      ledgerSweepMs: 60 * 60 * 1000, // tests sweep explicitly
    },
    dashboard: {
      // Off by default like the MCP surface; the dashboard rig turns it
      // on so the suites that never touch it keep their current shape.
      enabled: false,
      postLoginPath: "/",
      sessionMaxS: 12 * 3600,
      cookieSecure: false, // plain-http test server
      pageDefault: 50,
      pageMax: 200,
      batchMax: 10,
      // A-3: the production default. `ops` is the playbook's R3 and is
      // deliberately not `steward`, so the suites exercise the split
      // the gate asks for rather than a permissive test-only variant.
      adminRoles: ["ops"],
      // Short, because these suites host no runner: the probe's honest
      // "no verdict yet" is what they assert, and waiting a real minute
      // for it proves nothing extra.
      probeTimeoutS: 5,
    },
    ...overrides,
  };
  const notifier = new JobsNotifier(url);
  await notifier.start();
  let captured = "";
  const stream = { write: (chunk: string) => (captured += chunk) };
  const app = buildServer(cfg, pool, notifier, stream);
  await app.listen({ host: "127.0.0.1", port: 0 });
  const address = app.server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  return {
    cfg,
    pool,
    baseUrl: `http://127.0.0.1:${port}`,
    logs: () => captured,
    stop: async () => {
      await app.close();
      await notifier.stop();
      await pool.end();
      await drop();
    },
  };
}

/** Runs a connector through the existing local CLI harness (the C-2
 * byte-identity reference) and returns the emitted canonical bytes. */
export async function cliHarnessSnapshot(
  connectorSpec: string,
  config: Record<string, unknown>,
): Promise<Buffer> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-cli-"));
  try {
    const configFile = path.join(dir, "config.json");
    const outFile = path.join(dir, "out.json");
    await writeFile(configFile, JSON.stringify(config));
    await new Promise<void>((resolve, reject) => {
      const child = spawn(
        pythonPath(),
        ["-m", "connectors.sdk.local", connectorSpec, "--config", configFile, "--out", outFile],
        { cwd: repoRoot(), env: { ...process.env, PYTHONPATH: repoRoot() } },
      );
      let stderr = "";
      child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
      child.on("error", reject);
      child.on("close", (code) =>
        code === 0 ? resolve() : reject(new Error(`local CLI exited ${code}: ${stderr}`)),
      );
    });
    return await readFile(outFile);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

/** Verdict of the Python delivery gate over a snapshot file's bytes —
 * used to compute reference canonical-body hashes without any JS
 * re-serialization. */
export async function acceptVerdict(bytes: Buffer): Promise<Record<string, unknown>> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-verdict-"));
  try {
    const file = path.join(dir, "doc.json");
    await writeFile(file, bytes);
    return await new Promise((resolve, reject) => {
      const child = spawn(pythonPath(), ["-m", "snapshot.accept", file], {
        cwd: repoRoot(),
        env: { ...process.env, PYTHONPATH: repoRoot() },
      });
      let stdout = "";
      let stderr = "";
      child.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
      child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
      child.on("error", reject);
      child.on("close", (code) => {
        if (code === 0 || code === 1) resolve(JSON.parse(stdout));
        else reject(new Error(`accept exited ${code}: ${stderr}`));
      });
    });
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
