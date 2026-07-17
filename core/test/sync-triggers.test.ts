/**
 * SO-1 (webhook §4.2), SO-2 (policy edit → next tick), SO-9 (freshness
 * §8) and the secret-rotation exit criterion. One core + one scratch KB
 * for the file; each conformance case uses its own system name.
 */

import { createHash, randomBytes } from "node:crypto";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterAll, beforeAll, expect, it } from "vitest";
import { schedulerTick } from "../src/scheduler.js";
import { setHookSecret, upsertSyncSystem } from "../src/triggers.js";
import { WireClient } from "./fake-runner.js";
import { startCore, TEST_TOKEN, type TestCore } from "./helpers.js";
import { cleanupDir, initScratchKb, syncConfig, type ScratchKb } from "./sync-helpers.js";

const CANARY = "hook-canary-9c41f7d2ab";

let base: string;
let kb: ScratchKb;
let core: TestCore;
let client: WireClient;

function policyYaml(entries: Record<string, string[]>): string {
  const lines = ["systems:"];
  for (const [system, body] of Object.entries(entries)) {
    lines.push(`  ${system}:`);
    lines.push(...body.map((l) => `    ${l}`));
  }
  return lines.join("\n") + "\n";
}

async function setPolicy(entries: Record<string, string[]>): Promise<void> {
  await writeFile(
    path.join(kb.seedClone, ".contextlayer", "sync-policy.yaml"),
    policyYaml(entries),
  );
  kb.commitAll("policy edit");
}

const BASE_POLICY: Record<string, string[]> = {
  hookdemo: ["freshness_threshold: 30d", "triggers: {schedule: null, manual: true}"],
  scheddemo: ["freshness_threshold: 30d", "triggers: {schedule: null, manual: true}"],
  freshdemo: ["freshness_threshold: 30d", "triggers: {schedule: null, manual: true}"],
  schedfresh: ["freshness_threshold: 1h", "triggers: {schedule: 1h, manual: true}"],
};

async function insertAccepted(system: string, capturedAgoS: number): Promise<void> {
  await core.pool.query(
    `INSERT INTO accepted_snapshots (snapshot_id, system, snapshot_version,
       source_mode, connector_name, connector_version, captured_at, body,
       sha256, canonical_body_sha256, object_count)
     VALUES ($1, $2, '1', 'ddl-file', 'static-demo', '0.1.0',
             now() - make_interval(secs => $3), $4, $5, $5, 1)`,
    [
      randomBytes(8).toString("hex"),
      system,
      capturedAgoS,
      Buffer.from("{}"),
      randomBytes(32).toString("hex"),
    ],
  );
}

async function queuedJobs(system: string): Promise<Record<string, unknown>[]> {
  const { json } = await client.get(`/v1/jobs?system=${system}`);
  return json.jobs as Record<string, unknown>[];
}

beforeAll(async () => {
  base = await mkdtemp(path.join(tmpdir(), "cl-so-triggers-"));
  kb = await initScratchKb(base);
  const policyDir = path.join(kb.seedClone, ".contextlayer");
  await (await import("node:fs/promises")).mkdir(policyDir, { recursive: true });
  await setPolicy(BASE_POLICY);
  core = await startCore({});
  core.cfg.sync = syncConfig(kb, path.join(base, "workdir"));
  client = new WireClient(core.baseUrl, TEST_TOKEN);
  for (const system of Object.keys(BASE_POLICY)) {
    await upsertSyncSystem(core.pool, {
      system,
      connector_name: "static-demo",
      version_constraint: "*",
      payload: { config: { system, mode: "ddl-file" } },
    });
  }
}, 120_000);

afterAll(async () => {
  await core.stop();
  await cleanupDir(base);
});

async function postHook(
  system: string,
  secret: string | null,
  body: string = `{"canary":"${CANARY}"}`,
  contentType = "application/json",
): Promise<number> {
  const response = await fetch(`${core.baseUrl}/v1/hooks/${system}`, {
    method: "POST",
    headers: {
      "content-type": contentType,
      ...(secret !== null ? { "x-cl-hook-secret": secret } : {}),
    },
    body,
  });
  await response.text();
  return response.status;
}

it("SO-1: webhook — valid secret 202 + enqueued webhook trigger; bad secret 401; unknown 404; body never parsed or logged", async () => {
  const secret = randomBytes(32).toString("hex");
  await setHookSecret(core.pool, "hookdemo", createHash("sha256").update(secret).digest("hex"));

  expect(await postHook("hookdemo", secret)).toBe(202);
  const jobs = await queuedJobs("hookdemo");
  expect(jobs.length).toBe(1);
  expect((jobs[0]!.trigger as { kind: string }).kind).toBe("webhook");

  // invalid secret → 401, nothing new enqueued
  expect(await postHook("hookdemo", "wrong-" + secret)).toBe(401);
  expect(await postHook("hookdemo", null)).toBe(401);
  // unknown system → 404 (indistinguishable from not-configured, M-4)
  expect(await postHook("nosuchsystem", secret)).toBe(404);
  expect((await queuedJobs("hookdemo")).length).toBe(1);
  const merged = (await queuedJobs("hookdemo"))[0]!.triggers as unknown[];
  expect(merged.length).toBe(1); // 401s merged nothing into the trigger history

  // non-JSON content types are accepted and discarded on hook paths
  expect(await postHook("hookdemo", secret, "x=1&y=2", "application/x-www-form-urlencoded")).toBe(202);

  // Content-Length cap guards the socket (§4.2)
  expect(await postHook("hookdemo", secret, "x".repeat(65 * 1024))).toBe(413);

  // SY-2: the canary payload was never parsed, logged, or stored
  expect(core.logs()).not.toContain(CANARY);
  const { rows } = await core.pool.query(
    `SELECT coalesce(string_agg(jobs::text, ''), '') AS blob FROM jobs`,
  );
  expect(rows[0].blob).not.toContain(CANARY);
});

it("rotation: a new hook secret takes effect without restart", async () => {
  const first = randomBytes(32).toString("hex");
  await setHookSecret(core.pool, "hookdemo", createHash("sha256").update(first).digest("hex"));
  expect(await postHook("hookdemo", first)).toBe(202);

  const second = randomBytes(32).toString("hex");
  const action = await setHookSecret(
    core.pool,
    "hookdemo",
    createHash("sha256").update(second).digest("hex"),
  );
  expect(action).toBe("rotated");
  expect(await postHook("hookdemo", first)).toBe(401); // old secret dead
  expect(await postHook("hookdemo", second)).toBe(202); // same process, no restart
});

it("SO-2: a policy edit merged to the KB schedules per the new interval on the next tick", async () => {
  // tick with schedule: null → nothing scheduled for scheddemo
  await schedulerTick(core.pool, core.cfg, () => {});
  expect((await queuedJobs("scheddemo")).length).toBe(0);

  // merge a policy edit: 2h interval; snapshot is 3h old → due next tick
  await insertAccepted("scheddemo", 3 * 3600);
  await setPolicy({
    ...BASE_POLICY,
    scheddemo: ["freshness_threshold: 30d", "triggers: {schedule: 2h, manual: true}"],
  });
  await schedulerTick(core.pool, core.cfg, () => {});
  const jobs = await queuedJobs("scheddemo");
  expect(jobs.length).toBe(1);
  expect((jobs[0]!.trigger as { kind: string }).kind).toBe("schedule");

  // fresh snapshot → not due; the queued job gains no extra trigger
  await insertAccepted("scheddemo", 0);
  await schedulerTick(core.pool, core.cfg, () => {});
  const after = await queuedJobs("scheddemo");
  expect(after.length).toBe(1);
  expect((after[0]!.triggers as unknown[]).length).toBe(1);
});

it("SO-9: threshold crossing warns with mode guidance; next accepted snapshot clears; a dead schedule still warns", async () => {
  const eventCount = async (kind: string) =>
    Number(
      (
        await core.pool.query(
          `SELECT count(*) AS n FROM health_events WHERE kind = $1 AND system = 'freshdemo'`,
          [kind],
        )
      ).rows[0].n,
    );

  // age 2h, threshold 30d → no warning
  await insertAccepted("freshdemo", 2 * 3600);
  await schedulerTick(core.pool, core.cfg, () => {});
  let { rows } = await core.pool.query(
    `SELECT * FROM freshness_warnings WHERE system = 'freshdemo'`,
  );
  expect(rows.length).toBe(0);
  const raisedBefore = await eventCount("freshness_warning");
  const clearedBefore = await eventCount("freshness_cleared");

  // shrink the threshold below the current age → warning with manual-mode guidance
  await setPolicy({
    ...BASE_POLICY,
    freshdemo: ["freshness_threshold: 1h", "triggers: {schedule: null, manual: true}"],
  });
  await schedulerTick(core.pool, core.cfg, () => {});
  ({ rows } = await core.pool.query(
    `SELECT * FROM freshness_warnings WHERE system = 'freshdemo'`,
  ));
  expect(rows.length).toBe(1);
  expect(JSON.stringify(rows[0].detail)).toContain("re-submit");
  expect(await eventCount("freshness_warning")).toBe(raisedBefore + 1);

  // next accepted snapshot clears the warning
  await insertAccepted("freshdemo", 0);
  await schedulerTick(core.pool, core.cfg, () => {});
  ({ rows } = await core.pool.query(
    `SELECT * FROM freshness_warnings WHERE system = 'freshdemo'`,
  ));
  expect(rows.length).toBe(0);
  expect(await eventCount("freshness_cleared")).toBe(clearedBefore + 1);
  await setPolicy(BASE_POLICY); // restore

  // dead schedule (SY-7): scheduled system whose jobs never succeed —
  // snapshot 3h old vs 1h threshold warns exactly like a manual source
  await insertAccepted("schedfresh", 3 * 3600);
  await schedulerTick(core.pool, core.cfg, () => {});
  const dead = await core.pool.query(
    `SELECT * FROM freshness_warnings WHERE system = 'schedfresh'`,
  );
  expect(dead.rows.length).toBe(1);
  expect(JSON.stringify(dead.rows[0].detail)).toContain("scheduled every");
  // and the tick did (re-)trigger a snapshot job that nobody serves
  expect((await queuedJobs("schedfresh")).length).toBeGreaterThan(0);
});
