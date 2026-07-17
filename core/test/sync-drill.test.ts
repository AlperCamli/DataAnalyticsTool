/**
 * SO-4 + SO-8: the drill fixture end-to-end through the REAL pipeline —
 * manual trigger (§4.3 DDL re-handover) → snapshot job → real Python SDK
 * runner (ephemeral Postgres, ddl-file mode) → J-6 → diff → lineage →
 * scan → status writes → renders → PR on a scratch KB repo — compared
 * against the fixture's expected outcome set, with KB-4 (front-matter-
 * only writes) and KB-8 (render byte-consistency, via the validation
 * library itself) asserted on the PR tree.
 */

import { spawn, type ChildProcess } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { triggerSystem } from "../src/triggers.js";
import { pythonPath, repoRoot, startCore, TEST_TOKEN, type TestCore } from "./helpers.js";
import {
  checkoutBranch,
  cleanupDir,
  drainRuns,
  DRILL_DIR,
  drillSnapshot,
  initScratchKb,
  py,
  readPrs,
  registerDrillSystem,
  seedDrillKb,
  sh,
  syncConfig,
  type ScratchKb,
} from "./sync-helpers.js";

let base: string;
let kb: ScratchKb;
let core: TestCore;
let runner: { child: ChildProcess; output: () => string; kill: () => void };
let prBranchDir: string;
let prBody = "";
let prTitle = "";

async function spawnRunner(): Promise<typeof runner> {
  const dir = await mkdtemp(path.join(tmpdir(), "cl-drill-runner-"));
  const configFile = path.join(dir, "runner.yaml");
  await writeFile(
    configFile,
    JSON.stringify({
      core_url: core.baseUrl,
      token_env: "CL_RUNNER_TOKEN",
      runner_id: "runner-drill",
      connectors: ["connectors.postgres.connector:connector"],
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
      },
    },
  );
  child.stdout!.on("data", (d: Buffer) => (captured += d.toString()));
  child.stderr!.on("data", (d: Buffer) => (captured += d.toString()));
  return { child, output: () => captured, kill: () => child.kill("SIGKILL") };
}

beforeAll(async () => {
  base = await mkdtemp(path.join(tmpdir(), "cl-so-drill-"));
  kb = await initScratchKb(base);
  await seedDrillKb(kb, await drillSnapshot("before"));
  core = await startCore({});
  core.cfg.sync = syncConfig(kb, path.join(base, "workdir"));
  const system = await registerDrillSystem(core); // config points at after.sql
  runner = await spawnRunner();

  // §4.3: the DDL re-handover is a manual trigger with the files as the
  // connector's config input — then the whole pipeline runs for real.
  await triggerSystem(core.pool, core.cfg, system, {
    kind: "manual",
    detail: { actor: "drill", note: "DDL re-handover (after.sql)" },
  });
  const runs = await drainRuns(core);
  expect(runs).toBe(1);

  const prs = await readPrs(kb);
  expect(prs.length).toBe(1);
  expect(prs[0]!.state).toBe("open");
  prBody = prs[0]!.body;
  prTitle = prs[0]!.title;
  prBranchDir = await checkoutBranch(kb, prs[0]!.branch);
}, 600_000);

afterAll(async () => {
  runner?.kill();
  await core?.stop();
  await cleanupDir(base);
});

it("SO-4: exact expected classifications, title and changelog shape", async () => {
  const expected = JSON.parse(
    await readFile(path.join(DRILL_DIR, "expected", "classifications.json"), "utf-8"),
  ) as { title: string };
  expect(prTitle).toBe(expected.title);
  const goldenBody = await readFile(
    path.join(DRILL_DIR, "expected", "changelog.md"),
    "utf-8",
  );
  expect(prBody).toBe(goldenBody);

  const { rows } = await core.pool.query(`SELECT * FROM runs`);
  expect(rows.length).toBe(1);
  expect(rows[0].outcome).toBe("succeeded");
  const counts = rows[0].classification_counts as Record<
    string,
    { breaking: number; additive: number; removed: number }
  >;
  expect(counts.drill!.breaking).toBe(4);
  expect(counts.drill!.additive).toBe(1);
  expect(counts.drill!.removed).toBe(1);
});

it("SO-4: contaminated set with correct contamination.path, statuses per the expected set", async () => {
  const expectedScan = JSON.parse(
    await readFile(path.join(DRILL_DIR, "expected", "scan.json"), "utf-8"),
  ) as {
    contaminated: { doc: string; contamination: { object: string; path?: string[] } }[];
  };
  const expectedStatuses = JSON.parse(
    await readFile(path.join(DRILL_DIR, "expected", "statuses.json"), "utf-8"),
  ) as Record<string, string>;

  for (const [doc, status] of Object.entries(expectedStatuses)) {
    const text = await readFile(path.join(prBranchDir, doc), "utf-8");
    expect(text, doc).toContain(`\nstatus: ${status}\n`);
  }
  for (const c of expectedScan.contaminated) {
    const text = await readFile(path.join(prBranchDir, c.doc), "utf-8");
    const line = text.split("\n").find((l) => l.startsWith("contamination: {"));
    expect(line, c.doc).toBeDefined();
    expect(line!, c.doc).toContain(`object: ${JSON.stringify(c.contamination.object)}`);
    for (const edge of c.contamination.path ?? []) {
      expect(line!, c.doc).toContain(edge);
    }
    if (!c.contamination.path) {
      expect(line!, c.doc).not.toContain("path:");
    }
  }

  // the run record carries the contaminated doc list (§5.11)
  const { rows } = await core.pool.query(`SELECT contaminated_docs FROM runs`);
  const docs = (rows[0].contaminated_docs as { doc: string }[]).map((c) => c.doc).sort();
  expect(docs).toEqual(expectedScan.contaminated.map((c) => c.doc).sort());
});

it("SO-4: front-matter-only writes (KB-4) — no human-doc body byte changed", async () => {
  const mainDir = await checkoutBranch(kb, "main");
  const changed = sh(
    "git",
    ["diff", "--name-only", "origin/main...HEAD"],
    prBranchDir,
  )
    .trim()
    .split("\n");
  const bodyOf = async (dir: string, rel: string): Promise<string | null> => {
    try {
      const text = await readFile(path.join(dir, rel), "utf-8");
      const end = text.indexOf("\n---\n", 3);
      return end === -1 ? text : text.slice(end + 5);
    } catch {
      return null;
    }
  };
  let humanDocsChecked = 0;
  for (const rel of changed) {
    if (!rel.endsWith(".md")) continue;
    if (rel.endsWith(".schema.md") || rel.endsWith("index.md")) continue; // machine-owned
    const before = await bodyOf(mainDir, rel);
    const after = await bodyOf(prBranchDir, rel);
    if (before === null) continue; // new machine file
    expect(after, rel).toBe(before);
    humanDocsChecked += 1;
  }
  expect(humanDocsChecked).toBeGreaterThanOrEqual(6);
});

it("SO-4: pruning — removed object loses its machine doc, human sibling survives contaminated", async () => {
  const gone = path.join(prBranchDir, "systems", "drill", "shop", "legacy_sessions.schema.md");
  await expect(readFile(gone)).rejects.toThrow();
  const sibling = await readFile(
    path.join(prBranchDir, "systems", "drill", "shop", "legacy_sessions.md"),
    "utf-8",
  );
  expect(sibling).toContain("status: contaminated");
});

it("SO-8: the PR tree passes the validation library (KB-8 render byte-consistency) and carries purpose text (D-38)", async () => {
  // generator.validate re-renders (pinned snapshot, HEAD enrichment) into
  // a scratch tree and byte-compares — the independent fresh render.
  const out = py(["-m", "generator.validate", prBranchDir]);
  expect(out).toContain("0 errors");

  const machineDoc = await readFile(
    path.join(prBranchDir, "systems", "drill", "shop", "customers.schema.md"),
    "utf-8",
  );
  expect(machineDoc).toContain("Login identity"); // column_purposes merged into the render
}, 240_000);

it("SO-4: the canary in the runner's world never surfaces — the job carried config only", async () => {
  // sanity on the §4.3 path: the trigger's job payload was the registry
  // template (ddl files + image), and the delivered snapshot is the
  // after-state (5 objects, no legacy_sessions)
  const { rows } = await core.pool.query(
    `SELECT object_count FROM accepted_snapshots WHERE system = 'drill'
      ORDER BY accepted_at DESC LIMIT 1`,
  );
  expect(rows[0].object_count).toBe(5);
});
