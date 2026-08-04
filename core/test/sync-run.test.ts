/**
 * Run-pipeline conformance: SO-3 (coalescing), SO-5 (no-op), SO-6
 * (unparseable SQL), SO-7 (supersede), SO-10 (wheel carry), SO-11
 * (exclusion locality), SO-12 (deterministic re-run). Snapshots are
 * produced by the real connector harness (drill DDL, cached) and
 * delivered through the real job API by a scripted runner; each case
 * gets its own core + scratch KB.
 */

import { randomBytes } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeAll, expect, it } from "vitest";
import { remarkPending, triggerSystem, upsertSyncSystem } from "../src/triggers.js";
import { WireClient } from "./fake-runner.js";
import { cliHarnessSnapshot, sleep, startCore, TEST_OPS_TOKEN, TEST_TOKEN, type TestCore } from "./helpers.js";
import {
  checkoutBranch,
  cleanupDir,
  drainRuns,
  drillSnapshot,
  initScratchKb,
  py,
  readPrs,
  registerDrillSystem,
  seedDrillKb,
  serveSnapshotJob,
  sh,
  syncConfig,
  treeFingerprint,
  type ScratchKb,
} from "./sync-helpers.js";

let beforeBytes: Buffer;
let afterBytes: Buffer;

interface Rig {
  base: string;
  kb: ScratchKb;
  core: TestCore;
  client: WireClient;
}

const rigs: Rig[] = [];

async function makeRig(): Promise<Rig> {
  const base = await mkdtemp(path.join(tmpdir(), "cl-so-run-"));
  const kb = await initScratchKb(base);
  await seedDrillKb(kb, beforeBytes);
  const core = await startCore({});
  core.cfg.sync = syncConfig(kb, path.join(base, "workdir"));
  const client = new WireClient(core.baseUrl, TEST_TOKEN, TEST_OPS_TOKEN);
  await registerDrillSystem(core);
  const rig = { base, kb, core, client };
  rigs.push(rig);
  return rig;
}

async function trigger(rig: Rig, system = "drill"): Promise<void> {
  const { rows } = await rig.core.pool.query(
    `SELECT system, connector_name, version_constraint, payload FROM sync_systems WHERE system = $1`,
    [system],
  );
  await triggerSystem(rig.core.pool, rig.core.cfg, rows[0], {
    kind: "manual",
    detail: { actor: "so-tests" },
  });
}

async function runsOf(rig: Rig): Promise<Record<string, unknown>[]> {
  const { rows } = await rig.core.pool.query(`SELECT * FROM runs ORDER BY started_at, run_id`);
  return rows;
}

function remoteBranches(kb: ScratchKb): string[] {
  return sh("git", ["ls-remote", "--heads", kb.remote])
    .split("\n")
    .filter(Boolean)
    .map((l) => l.split("refs/heads/")[1]!);
}

beforeAll(async () => {
  [beforeBytes, afterBytes] = await Promise.all([
    drillSnapshot("before"),
    drillSnapshot("after"),
  ]);
}, 300_000);

afterEach(async () => {
  while (rigs.length > 0) {
    const rig = rigs.pop()!;
    await rig.core.stop();
    await cleanupDir(rig.base);
  }
});

it("SO-5: unchanged snapshot → no-op run record, no branch, no PR", async () => {
  const rig = await makeRig();
  await trigger(rig);
  const serve = serveSnapshotJob(rig.client, "postgres", beforeBytes);
  const runs = await drainRuns(rig.core);
  await serve;
  expect(runs).toBe(1);
  const records = await runsOf(rig);
  expect(records.length).toBe(1);
  expect(records[0]!.outcome).toBe("no-op");
  expect(remoteBranches(rig.kb)).toEqual(["main"]);
  expect(await readPrs(rig.kb)).toEqual([]);
}, 120_000);

it("SO-3: triggers during a running run coalesce into exactly one follow-up covering all pending systems", async () => {
  const rig = await makeRig();
  for (const system of ["demo2", "demo3"]) {
    await upsertSyncSystem(rig.core.pool, {
      system,
      connector_name: "static-demo",
      version_constraint: "*",
      payload: { config: { system, mode: "ddl-file" } },
    });
  }
  await trigger(rig, "drill");
  const drain = drainRuns(rig.core); // run 1 blocks awaiting drill acquisition

  // wait until run 1 has pinned (pending consumed), then trigger two more
  for (;;) {
    const { rows } = await rig.core.pool.query(`SELECT 1 FROM runs`);
    if (rows.length > 0) break;
    await sleep(50);
  }
  await trigger(rig, "demo2");
  await trigger(rig, "demo3");

  await serveSnapshotJob(rig.client, "postgres", beforeBytes);
  const demo2Bytes = await cliHarnessSnapshot("connectors.static_demo.connector:connector", {
    system: "demo2",
    mode: "ddl-file",
  });
  const demo3Bytes = await cliHarnessSnapshot("connectors.static_demo.connector:connector", {
    system: "demo3",
    mode: "ddl-file",
  });
  await serveSnapshotJob(rig.client, "static-demo", demo2Bytes);
  await serveSnapshotJob(rig.client, "static-demo", demo3Bytes);

  const runs = await drain;
  expect(runs).toBe(2); // the storm yields the running run + exactly one follow-up
  const records = await runsOf(rig);
  expect(records.length).toBe(2);
  const followUp = records[1]!;
  const systems = followUp.systems as { included: string[] };
  expect(systems.included).toEqual(expect.arrayContaining(["demo2", "demo3"]));
  expect(followUp.outcome).toBe("succeeded"); // new systems are additive drift
}, 240_000);

it("SO-7: a second run restates the still-true picture and supersedes the open breaking PR", async () => {
  const rig = await makeRig();
  await trigger(rig);
  const serve1 = serveSnapshotJob(rig.client, "postgres", afterBytes);
  await drainRuns(rig.core);
  await serve1;
  let prs = await readPrs(rig.kb);
  expect(prs.length).toBe(1);
  const first = prs[0]!;
  expect(first.state).toBe("open");
  expect(first.title).toContain("breaking");

  // drift persists (the PR is unmerged); a re-trigger restates it
  await trigger(rig);
  const serve2 = serveSnapshotJob(rig.client, "postgres", afterBytes);
  await drainRuns(rig.core);
  await serve2;
  prs = await readPrs(rig.kb);
  expect(prs.length).toBe(2);
  const [oldPr, newPr] = [prs[0]!, prs[1]!];
  expect(newPr.state).toBe("open");
  expect(newPr.title).toBe(first.title); // the same still-true picture
  expect(oldPr.state).toBe("closed");
  expect(oldPr.comments.join(" ")).toContain(newPr.url); // successor link
  expect(remoteBranches(rig.kb)).toEqual(["main", newPr.branch]); // old branch deleted
}, 240_000);

it("SO-6: unparseable definition → run failed, no PR, HEAD graph byte-unchanged, health names the definition", async () => {
  const rig = await makeRig();
  // craft a delivery whose changed view definition cannot parse
  const badFile = path.join(rig.base, "bad.json");
  await writeFile(path.join(rig.base, "after.json"), afterBytes);
  py([
    "-c",
    `
import json
from snapshot.hashing import schema_hash
doc = json.load(open(${JSON.stringify(path.join(rig.base, "after.json"))}))
obj = next(o for o in doc["objects"] if o["name"] == "v_order_totals")
obj["stats"]["definition"] = "SELECT ??? FROM ((("
obj["schema_hash"] = schema_hash(obj)
json.dump(doc, open(${JSON.stringify(badFile)}, "w"))
`,
  ]);
  const graphBefore = await readFile(
    path.join(await checkoutBranch(rig.kb, "main"), "lineage", "graph.json"),
  );

  await trigger(rig);
  const serve = serveSnapshotJob(rig.client, "postgres", await readFile(badFile));
  await drainRuns(rig.core);
  await serve;

  const records = await runsOf(rig);
  expect(records[0]!.outcome).toBe("failed");
  expect((records[0]!.detail as { stage: string }).stage).toBe("lineage");
  expect(await readPrs(rig.kb)).toEqual([]);
  expect(remoteBranches(rig.kb)).toEqual(["main"]);
  const { rows } = await rig.core.pool.query(
    `SELECT detail FROM health_events WHERE kind = 'sync_lineage_failed'`,
  );
  expect(rows.length).toBe(1);
  expect(JSON.stringify(rows[0].detail)).toContain("v_order_totals");
  const graphAfter = await readFile(
    path.join(await checkoutBranch(rig.kb, "main"), "lineage", "graph.json"),
  );
  expect(graphAfter.equals(graphBefore)).toBe(true);
}, 240_000);

it("SO-11: acquisition failure excludes one system and ships the other; post-acquisition failure fails the whole run", async () => {
  const rig = await makeRig();
  await upsertSyncSystem(rig.core.pool, {
    system: "demo2",
    connector_name: "static-demo",
    version_constraint: "*",
    payload: { config: { system: "demo2", mode: "ddl-file" } },
  });
  await trigger(rig, "drill");
  await trigger(rig, "demo2");
  const serveGood = serveSnapshotJob(rig.client, "postgres", afterBytes);
  // demo2's delivery fails J-6 → dead-letter → acquisition failure
  const serveBad = (async () => {
    const { status, json } = await rig.client.claim({
      runner_id: "runner-bad",
      connectors: [{ name: "static-demo", version: "0.1.0", types: ["snapshot"] }],
      classes: ["batch"],
      wait_s: 10,
    });
    expect(status).toBe(200);
    const jobId = json.job_id as string;
    const lease = (json.lease as { token: string }).token;
    await rig.client.start(jobId, lease);
    const done = await rig.client.completeRaw(jobId, lease, `{"not": "a snapshot"}`);
    expect(done.status).toBe(422);
  })();
  await Promise.all([serveGood, serveBad]);
  await drainRuns(rig.core);

  const records = await runsOf(rig);
  expect(records.length).toBe(1);
  expect(records[0]!.outcome).toBe("succeeded");
  const systems = records[0]!.systems as {
    included: string[];
    excluded: { system: string; reason: string }[];
  };
  expect(systems.included).toContain("drill");
  expect(systems.excluded.map((e) => e.system)).toEqual(["demo2"]);
  expect(systems.excluded[0]!.reason).toContain("dead_lettered");
  const prs = await readPrs(rig.kb);
  expect(prs.length).toBe(1);
  expect(prs[0]!.body).toContain("Systems excluded from this run");
  const { rows } = await rig.core.pool.query(
    `SELECT * FROM health_events WHERE kind = 'sync_system_excluded' AND system = 'demo2'`,
  );
  expect(rows.length).toBe(1);

  // post-acquisition failure (injected stage failure) → whole run fails, no PR
  const rig2 = await makeRig();
  await trigger(rig2);
  const serve2 = serveSnapshotJob(rig2.client, "postgres", afterBytes);
  rig2.core.cfg.sync.pythonCmd = ["false"]; // every Python stage now fails
  await drainRuns(rig2.core);
  await serve2;
  const records2 = await runsOf(rig2);
  expect(records2[0]!.outcome).toBe("failed");
  expect((records2[0]!.detail as { stage: string }).stage).toBe("diff");
  expect(await readPrs(rig2.kb)).toEqual([]);
  expect(remoteBranches(rig2.kb)).toEqual(["main"]);
}, 240_000);

it("SO-12: a failed run re-run over identical pinned inputs yields byte-identical branch content", async () => {
  const rig = await makeRig();
  await trigger(rig);
  const serve = serveSnapshotJob(rig.client, "postgres", afterBytes);
  await serve; // acquisition instant on the actual runs below

  const { rows: pendingRows } = await rig.core.pool.query(
    `SELECT system, triggers, job_id FROM sync_pending`,
  );
  const pendingSnapshot = pendingRows as { system: string; triggers: []; job_id: string }[];

  // sabotage the PR provider: the store path is a directory → open fails
  await mkdir(rig.kb.prsFile, { recursive: true });
  await drainRuns(rig.core);
  let records = await runsOf(rig);
  expect(records[0]!.outcome).toBe("failed");
  expect((records[0]!.detail as { stage: string }).stage).toBe("pr");
  expect(remoteBranches(rig.kb)).toEqual(["main"]); // §6: branch deleted
  const { rows: gitHealth } = await rig.core.pool.query(
    `SELECT severity FROM health_events WHERE kind = 'sync_git_failed'`,
  );
  expect(gitHealth).toEqual([{ severity: "warning" }]);

  // recovery is "just run it again" (SY-1): same pinned inputs, twice
  await rm(rig.kb.prsFile, { recursive: true, force: true });
  await remarkPending(rig.core.pool, pendingSnapshot);
  await drainRuns(rig.core);
  records = await runsOf(rig);
  expect(records[1]!.outcome).toBe("succeeded");
  const branch2 = (await readPrs(rig.kb)).at(-1)!.branch;
  const fp2 = treeFingerprint(rig.kb, branch2);

  await remarkPending(rig.core.pool, pendingSnapshot);
  await drainRuns(rig.core);
  records = await runsOf(rig);
  expect(records[2]!.outcome).toBe("succeeded");
  const branch3 = (await readPrs(rig.kb)).at(-1)!.branch;
  const fp3 = treeFingerprint(rig.kb, branch3);

  expect(branch3).not.toBe(branch2); // different run ids…
  expect(fp3).toBe(fp2); // …byte-identical tree content
}, 240_000);

it("SO-10: wheel version mismatch → the next sync PR leads with the wheel commit; manifest is the only pin, no workflow file touched (R-6b); wheel-only manual run supported", async () => {
  const rig = await makeRig();
  // seed KB carries an old vendored wheel + manifest + CI pin
  const vendor = path.join(rig.kb.seedClone, ".github", "vendor");
  await mkdir(vendor, { recursive: true });
  await writeFile(path.join(vendor, "contextlayer_snapshot-0.3.0-py3-none-any.whl"), "old-wheel");
  await writeFile(
    path.join(vendor, "VENDOR-MANIFEST.yaml"),
    "# Provenance for the vendored validation library.\n\n" +
      "package: contextlayer-snapshot\nversion: 0.3.0\n" +
      "wheel: contextlayer_snapshot-0.3.0-py3-none-any.whl\n" +
      "sha256: aaaa\nplatform_commit: 0000000\nbuilt: 2026-07-01\n" +
      "built_by: seed\nsource: platform repo\n" +
      "runtime_deps_pinned_in: this file (runtime_deps)\n" +
      "runtime_deps:\n  - jsonschema==4.26.0\n  - PyYAML==6.0.3\n",
  );
  // R-6(b): the workflow reads the wheel filename out of the manifest, so
  // it carries no version at all. The carry must leave it untouched.
  const workflows = path.join(rig.kb.seedClone, ".github", "workflows");
  await mkdir(workflows, { recursive: true });
  const CI_YAML =
    "steps:\n" +
    "  - run: |\n" +
    "      WHEEL=$(sed -n 's/^wheel: //p' .github/vendor/VENDOR-MANIFEST.yaml)\n" +
    "      pip install --no-deps \".github/vendor/$WHEEL\"\n";
  await writeFile(path.join(workflows, "kb-ci.yml"), CI_YAML);
  rig.kb.commitAll("seed vendored wheel");

  const wheelPath = path.join(rig.base, "contextlayer_snapshot-0.4.0-py3-none-any.whl");
  await writeFile(wheelPath, "new-wheel-bytes");
  Object.assign(rig.core.cfg.sync, {
    wheelPath,
    wheelVersion: "0.4.0",
    platformCommit: "cafe1234",
    wheelBuilt: "2026-07-17",
  });

  await trigger(rig);
  const serve = serveSnapshotJob(rig.client, "postgres", afterBytes);
  await drainRuns(rig.core);
  await serve;

  const prs = await readPrs(rig.kb);
  expect(prs.length).toBe(1);
  expect(prs[0]!.body).toContain("0.3.0 → 0.4.0");
  const clone = await checkoutBranch(rig.kb, prs[0]!.branch);
  const log = sh("git", ["log", "--format=%s", "origin/main..HEAD"], clone)
    .trim()
    .split("\n");
  expect(log.length).toBe(2);
  expect(log[1]).toContain("vendored validation wheel 0.4.0"); // first commit of the PR
  const wheelFiles = sh(
    "git",
    ["show", "--name-only", "--format=", log[1]!.length > 0 ? "HEAD~1" : "HEAD"],
    clone,
  )
    .trim()
    .split("\n");
  const manifest = await readFile(path.join(clone, ".github", "vendor", "VENDOR-MANIFEST.yaml"), "utf-8");
  expect(manifest).toContain("version: 0.4.0");
  expect(manifest).toContain("platform_commit: cafe1234");
  expect(manifest).toContain("built: 2026-07-17");
  expect(manifest).toContain("# Provenance for the vendored validation library.");
  expect(manifest).toContain("wheel: contextlayer_snapshot-0.4.0-py3-none-any.whl");
  // KB-owned runtime pins survive the carry — dropping them would leave
  // CI installing nothing at all.
  expect(manifest).toContain("jsonschema==4.26.0");
  expect(manifest).toContain("PyYAML==6.0.3");

  // R-6(b): the wheel commit touches vendor files only. No workflow file
  // is written, so the sync identity needs no `workflow` write scope —
  // asserted, because "we don't need it" is the kind of claim that rots.
  expect(wheelFiles.every((f) => f.startsWith(".github/vendor/"))).toBe(true);
  expect(wheelFiles.some((f) => f.includes("workflows/"))).toBe(false);
  const ci = await readFile(path.join(clone, ".github", "workflows", "kb-ci.yml"), "utf-8");
  expect(ci).toBe(CI_YAML); // byte-identical to what was seeded
  const branchFiles = sh("git", ["ls-tree", "-r", "--name-only", "HEAD", ".github/vendor"], clone);
  expect(branchFiles).not.toContain("0.3.0"); // old wheel removed

  // wheel-only: no drift pending, manual sync forces the carry.
  // Merge the open PR first so the drift is no longer outstanding.
  sh("git", ["fetch", "origin", prs[0]!.branch], rig.kb.seedClone);
  sh("git", ["merge", "--ff-only", "FETCH_HEAD"], rig.kb.seedClone);
  sh("git", ["push", "origin", "main"], rig.kb.seedClone);
  // re-stage the mismatch: the KB now has 0.4.0; pretend a 0.5.0 release
  const wheel5 = path.join(rig.base, "contextlayer_snapshot-0.5.0-py3-none-any.whl");
  await writeFile(wheel5, "newer-wheel-bytes");
  Object.assign(rig.core.cfg.sync, { wheelPath: wheel5, wheelVersion: "0.5.0" });

  await trigger(rig);
  const serve2 = serveSnapshotJob(rig.client, "postgres", afterBytes);
  await drainRuns(rig.core);
  await serve2;
  const prs2 = await readPrs(rig.kb);
  const wheelOnly = prs2.at(-1)!;
  expect(wheelOnly.title).toContain("wheel-only update to 0.5.0");
  expect(wheelOnly.body).toContain("Wheel-only run");
  const clone2 = await checkoutBranch(rig.kb, wheelOnly.branch);
  const log2 = sh("git", ["log", "--format=%s", "origin/main..HEAD"], clone2).trim().split("\n");
  expect(log2.length).toBe(1);
  expect(log2[0]).toContain("vendored validation wheel 0.5.0");

  // D-98 task 0: the run *record* also says what shape the run was —
  // a genuine wheel-only run is wheel_only, and not graph_only.
  const records = await runsOf(rig);
  const detail = records.at(-1)!.detail as { wheel_only?: boolean; graph_only?: boolean };
  expect(detail.wheel_only).toBe(true);
  expect(detail.graph_only).toBe(false);
}, 300_000);

it("D-98 task 0 (ops half of D-97.1): a graph-only run's record says graph_only, never wheel_only", async () => {
  const rig = await makeRig();
  // A publish attestation whose edge is not in the HEAD graph makes a
  // regeneration pending with no snapshot drift (CP-7 F-4) — the exact
  // shape run 01KYVXMQ8Q0BAHTKC8WM5WBK5S stored as "wheel-only".
  await rig.core.pool.query(
    `INSERT INTO lineage_attestations
       (source_fqn, target_fqn, operation, evidence, source_meta, target_meta)
     VALUES ($1, $2, 'ingest', $3, NULL, $4)`,
    [
      "drill.public.orders",
      "powerbi.report.d97-ops-half",
      JSON.stringify({ tier: "pipeline-tool", ref: "gateway:d97-test" }),
      JSON.stringify({ resolved: true, kind: "report", schema: null, name: "d97-ops-half" }),
    ],
  );

  await trigger(rig);
  const serve = serveSnapshotJob(rig.client, "postgres", beforeBytes);
  await drainRuns(rig.core);
  await serve;

  const prs = await readPrs(rig.kb);
  expect(prs.length).toBe(1);
  expect(prs[0]!.title).toBe("sync: 0 breaking, 0 additive (report lineage only)");
  expect(prs[0]!.body).toContain("Graph-only run");
  expect(prs[0]!.body).not.toContain("Wheel-only");

  const records = await runsOf(rig);
  expect(records.length).toBe(1);
  expect(records[0]!.outcome).toBe("succeeded");
  const detail = records[0]!.detail as { wheel_only?: boolean; graph_only?: boolean };
  expect(detail.graph_only).toBe(true);
  expect(detail.wheel_only).toBe(false);
}, 300_000);
