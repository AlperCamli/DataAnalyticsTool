/**
 * Rig for the SO conformance tests: a scratch KB repo (bare + local PR
 * store — the `local` provider, same pipeline code as deployed), drill
 * snapshot production through the real connector harness (cached on
 * disk per DDL content), and a scripted fake runner that delivers
 * harness bytes through the real job API (J-6 and all).
 */

import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import type { CoreConfig, SyncConfig } from "../src/config.js";
import { createProvider } from "../src/gitkb.js";
import { runPendingRuns, type RunDeps } from "../src/pipeline.js";
import { upsertSyncSystem, type SyncSystem } from "../src/triggers.js";
import { WireClient } from "./fake-runner.js";
import { cliHarnessSnapshot, pythonPath, repoRoot, type TestCore } from "./helpers.js";

export const DRILL_DIR = path.join(repoRoot(), "fixtures", "drill");

// ---------------------------------------------------------------------------
// shell helpers (test-side git is plain execFileSync; the code under test
// uses src/gitkb.ts)

export function sh(cmd: string, args: string[], cwd?: string): string {
  return execFileSync(cmd, args, { cwd, encoding: "utf-8" });
}

const GIT_ID = ["-c", "user.name=drill-customer", "-c", "user.email=customer@drill.invalid"];

export interface ScratchKb {
  /** bare repo path — the SYNC_GIT_REMOTE */
  remote: string;
  /** local provider PR store path */
  prsFile: string;
  /** working clone the seed was committed from */
  seedClone: string;
  headSha: () => string;
  /** commit + push the seed clone's current tree to main */
  commitAll: (message: string) => string;
}

export async function initScratchKb(base: string): Promise<ScratchKb> {
  const remote = path.join(base, "kb.git");
  const seedClone = path.join(base, "kb-seed-clone");
  await mkdir(remote, { recursive: true });
  sh("git", ["init", "--bare", "--quiet", "-b", "main", remote]);
  sh("git", ["clone", "--quiet", remote, seedClone]);
  return {
    remote,
    prsFile: path.join(base, "kb.prs.json"),
    seedClone,
    headSha: () => sh("git", ["ls-remote", remote, "refs/heads/main"]).split(/\s/)[0]!,
    commitAll: (message: string) => {
      sh("git", ["add", "-A"], seedClone);
      sh("git", [...GIT_ID, "commit", "--quiet", "--allow-empty", "-m", message], seedClone);
      sh("git", ["push", "--quiet", "origin", "main"], seedClone);
      return sh("git", ["rev-parse", "HEAD"], seedClone).trim();
    },
  };
}

// ---------------------------------------------------------------------------
// drill snapshots via the real connector harness (ephemeral Postgres),
// cached on disk keyed by DDL bytes so parallel test files share spins

export async function drillSnapshot(which: "before" | "after"): Promise<Buffer> {
  const ddl = path.join(DRILL_DIR, "ddl", `${which}.sql`);
  const key = createHash("sha256").update(await readFile(ddl)).digest("hex").slice(0, 16);
  const cache = path.join(tmpdir(), `cl-drill-snap-${key}.json`);
  try {
    return await readFile(cache);
  } catch {
    // not cached yet
  }
  const bytes = await cliHarnessSnapshot("connectors.postgres.connector:connector", {
    system: "drill",
    mode: "ddl-file",
    ddl_files: [ddl],
    image: "postgres:16",
  });
  const tmp = `${cache}.${process.pid}`;
  await writeFile(tmp, bytes);
  await rename(tmp, cache);
  return bytes;
}

/** Python stage CLI, run exactly as the pipeline runs it. */
export function py(args: string[], cwd?: string): string {
  return execFileSync(pythonPath(), args, {
    cwd: cwd ?? repoRoot(),
    encoding: "utf-8",
    env: { ...process.env, PYTHONPATH: repoRoot() },
  });
}

/**
 * Seed the scratch KB with the drill baseline: kb-seed fragment + pinned
 * before-snapshot + machine render + lineage graph, committed to main.
 */
export async function seedDrillKb(kb: ScratchKb, beforeBytes: Buffer): Promise<string> {
  await cp(path.join(DRILL_DIR, "kb-seed"), kb.seedClone, { recursive: true });
  const pin = path.join(kb.seedClone, ".contextlayer", "snapshots", "drill.json");
  await mkdir(path.dirname(pin), { recursive: true });
  await writeFile(pin, beforeBytes);
  py(["-m", "generator.render", pin, "--out", kb.seedClone]);
  py(["-m", "lineage", pin, "--kb", kb.seedClone]);
  return kb.commitAll("drill: seed KB (baseline handover)");
}

// ---------------------------------------------------------------------------
// core config + pipeline driving

export function syncConfig(kb: ScratchKb, workdir: string, extra: Partial<SyncConfig> = {}): SyncConfig {
  return {
    enabled: true,
    gitRemote: kb.remote,
    gitToken: "",
    gitProvider: "local",
    gitApiBase: "https://api.github.invalid",
    baseBranch: "main",
    committerName: "contextlayer-sync",
    committerEmail: "sync@contextlayer.invalid",
    pythonCmd: [pythonPath()],
    workdir,
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
    ...extra,
  };
}

export function runDeps(core: TestCore): RunDeps {
  return {
    pool: core.pool,
    cfg: core.cfg,
    provider: createProvider(core.cfg.sync),
    log: () => {},
  };
}

export async function drainRuns(core: TestCore): Promise<number> {
  return runPendingRuns(runDeps(core));
}

export const DRILL_SYSTEM: SyncSystem = {
  system: "drill",
  connector_name: "postgres",
  version_constraint: "*",
  payload: {
    config: {
      system: "drill",
      mode: "ddl-file",
      ddl_files: [path.join(DRILL_DIR, "ddl", "after.sql")],
      image: "postgres:16",
    },
  },
};

export async function registerDrillSystem(
  core: TestCore,
  overrides: Partial<SyncSystem> = {},
): Promise<SyncSystem> {
  const system = { ...DRILL_SYSTEM, ...overrides };
  await upsertSyncSystem(core.pool, system);
  return system;
}

/**
 * Scripted runner: claim the queued snapshot job for `system` and
 * deliver `bytes` verbatim through the real complete path (J-6 gate).
 */
export async function serveSnapshotJob(
  client: WireClient,
  connectorName: string,
  bytes: Buffer,
  runnerId = "runner-sync-test",
): Promise<{ jobId: string; snapshotId: string }> {
  const deadline = Date.now() + 30_000;
  for (;;) {
    const { status, json } = await client.claim({
      runner_id: runnerId,
      connectors: [{ name: connectorName, version: "0.1.0", types: ["snapshot"] }],
      classes: ["batch"],
      wait_s: 2,
    });
    if (status === 200) {
      const jobId = json.job_id as string;
      const lease = (json.lease as { token: string }).token;
      await client.start(jobId, lease);
      const done = await client.completeRaw(jobId, lease, bytes.toString("utf-8"));
      if (done.status !== 200) {
        throw new Error(`delivery rejected: ${done.status} ${JSON.stringify(done.json)}`);
      }
      return { jobId, snapshotId: done.json.snapshot_id as string };
    }
    if (Date.now() > deadline) throw new Error("no job to claim within 30s");
  }
}

// ---------------------------------------------------------------------------
// assertions over the scratch repo / PR store

export interface LocalPr {
  number: number;
  url: string;
  branch: string;
  title: string;
  body: string;
  labels: string[];
  state: "open" | "closed";
  comments: string[];
}

export async function readPrs(kb: ScratchKb): Promise<LocalPr[]> {
  try {
    return (JSON.parse(await readFile(kb.prsFile, "utf-8")) as { prs: LocalPr[] }).prs;
  } catch {
    return [];
  }
}

/** Checkout a branch of the scratch remote into a temp dir. */
export async function checkoutBranch(kb: ScratchKb, branch: string): Promise<string> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-kb-checkout-"));
  sh("git", ["clone", "--quiet", "--branch", branch, kb.remote, path.join(dir, "kb")]);
  return path.join(dir, "kb");
}

/** Deterministic content fingerprint of a branch tree (SO-12). */
export function treeFingerprint(kb: ScratchKb, branch: string): string {
  const dir = execFileSync("mktemp", ["-d"], { encoding: "utf-8" }).trim();
  sh("git", ["clone", "--quiet", "--branch", branch, kb.remote, path.join(dir, "t")]);
  const listing = sh(
    "git",
    ["-C", path.join(dir, "t"), "ls-tree", "-r", "HEAD", "--format=%(objectname) %(path)"],
  );
  return createHash("sha256").update(listing).digest("hex");
}

export async function cleanupDir(dir: string): Promise<void> {
  await rm(dir, { recursive: true, force: true });
}
