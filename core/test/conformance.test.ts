/**
 * Job-protocol conformance (spec §10) — the core-side surface, driven
 * over the real wire by a scripted runner client. JC-4 and JC-8 need
 * real runner processes and live in e2e.test.ts; JC-10 is deferred
 * (no blocked-producer surface until the gateway, CP-6).
 */

import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { sweepExpiredLeases } from "../src/queue.js";
import { DEMO_DECLARATION, WireClient } from "./fake-runner.js";
import { cliHarnessSnapshot, sleep, startCore, TEST_TOKEN, type TestCore } from "./helpers.js";

let core: TestCore;
let client: WireClient;
/** Canonical static-demo snapshot bytes per system, from the CLI harness. */
const demoBytes = new Map<string, string>();

async function demoSnapshot(system: string): Promise<string> {
  if (!demoBytes.has(system)) {
    const bytes = await cliHarnessSnapshot("connectors.static_demo.connector:connector", {
      system,
      mode: "ddl-file",
    });
    demoBytes.set(system, bytes.toString("utf-8"));
  }
  return demoBytes.get(system)!;
}

function snapshotJob(system: string, extras: Record<string, unknown> = {}) {
  return {
    type: "snapshot",
    system,
    connector: { name: "static-demo", version_constraint: ">=0.1 <0.2" },
    payload: { config: { system, mode: "ddl-file" } },
    trigger: { kind: "manual", detail: "conformance" },
    ...extras,
  };
}

const claimBody = (extras: Record<string, unknown> = {}) => ({
  runner_id: "runner-t1",
  connectors: DEMO_DECLARATION,
  classes: ["batch"],
  wait_s: 0,
  ...extras,
});

async function forceLeaseExpiry(jobId: string): Promise<void> {
  await core.pool.query(
    `UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE job_id = $1`,
    [jobId],
  );
  await sweepExpiredLeases(core.pool, core.cfg);
}

beforeAll(async () => {
  core = await startCore();
  client = new WireClient(core.baseUrl, TEST_TOKEN);
});

afterAll(async () => {
  await core.stop();
});

// Claims match on connector name, which every test here shares — park any
// job a test left non-terminal so it can't be claimed by the next one.
afterEach(async () => {
  await core.pool.query(
    `UPDATE jobs SET state = 'cancelled', lease_token = NULL, finished_at = now()
      WHERE state IN ('queued', 'leased', 'running')`,
  );
});

describe("auth (J-8)", () => {
  it("rejects missing and unknown bearer tokens", async () => {
    const anonymous = new WireClient(core.baseUrl, "");
    expect((await anonymous.claim(claimBody())).status).toBe(401);
    const wrong = new WireClient(core.baseUrl, "nope");
    expect((await wrong.enqueue(snapshotJob("auth-x"))).status).toBe(401);
  });

  it("enforces runner binding on bound tokens", async () => {
    const bound = new WireClient(core.baseUrl, "bound-token");
    const mismatched = await bound.claim(claimBody({ runner_id: "runner-other" }));
    expect(mismatched.status).toBe(403);
    const matched = await bound.claim(claimBody({ runner_id: "runner-bound" }));
    expect(matched.status).toBe(204);
  });

  it("leaves the health probe open", async () => {
    const response = await fetch(`${core.baseUrl}/healthz`);
    expect(response.status).toBe(200);
    const body = (await response.json()) as { status: string };
    expect(body.status).toBe("ok");
  });
});

describe("enqueue", () => {
  it("rejects unknown types, bad triggers, bad ranges", async () => {
    for (const bad of [
      { ...snapshotJob("enq-a"), type: "mystery" },
      { ...snapshotJob("enq-a"), trigger: { kind: "cron" } },
      { ...snapshotJob("enq-a"), connector: { name: "x", version_constraint: "not-a-range" } },
      { ...snapshotJob("enq-a"), system: "" },
    ]) {
      const { status, json } = await client.enqueue(bad);
      expect(status, JSON.stringify(json)).toBe(400);
    }
  });

  it("applies §4.2 class defaults", async () => {
    const { json } = await client.enqueue(snapshotJob("enq-defaults"));
    const job = (await client.job(json.job_id as string)).json;
    expect(job.class).toBe("batch");
    expect(job.priority).toBe(50);
    expect(job.max_attempts).toBe(5);
    expect(job.deadline_s).toBe(3600);
  });
});

describe("JC-1: claim honors connector name, version constraint, class", () => {
  it("matches only a fully compatible declaration", async () => {
    const { json } = await client.enqueue(snapshotJob("jc1"));
    const jobId = json.job_id as string;

    const wrongName = await client.claim(
      claimBody({ connectors: [{ name: "other", version: "0.1.0" }] }),
    );
    expect(wrongName.status).toBe(204);

    const wrongVersion = await client.claim(
      claimBody({ connectors: [{ name: "static-demo", version: "0.2.0" }] }),
    );
    expect(wrongVersion.status).toBe(204);

    const wrongClass = await client.claim(claimBody({ classes: ["interactive"] }));
    expect(wrongClass.status).toBe(204);

    // additive per-connector type filter
    const wrongType = await client.claim(
      claimBody({
        connectors: [{ name: "static-demo", version: "0.1.0", types: ["usage"] }],
      }),
    );
    expect(wrongType.status).toBe(204);

    const match = await client.claim(claimBody());
    expect(match.status).toBe(200);
    expect(match.json.job_id).toBe(jobId);
    expect(match.json.lease).toMatchObject({ ttl_s: 60 });
    expect(match.json.trigger).toMatchObject({ kind: "manual", detail: "conformance" });
  });
});

describe("JC-2: racing claims grant exactly one lease", () => {
  it("two concurrent claims, one job", async () => {
    await client.enqueue(snapshotJob("jc2"));
    const [a, b] = await Promise.all([
      client.claim(claimBody({ runner_id: "racer-a", wait_s: 1 })),
      client.claim(claimBody({ runner_id: "racer-b", wait_s: 1 })),
    ]);
    const statuses = [a.status, b.status].sort();
    expect(statuses).toEqual([200, 204]);
  });

  it("long-poll claim is woken by a later enqueue", async () => {
    const pending = client.claim(claimBody({ runner_id: "waiter", wait_s: 5 }));
    await sleep(150);
    await client.enqueue(snapshotJob("jc2-wake"));
    const claimed = await pending;
    expect(claimed.status).toBe(200);
    expect(claimed.json.system).toBe("jc2-wake");
  });
});

describe("JC-3: lease expiry and stale-lease rejection", () => {
  it("missed heartbeats requeue with attempt+1; stale calls get 409", async () => {
    await client.enqueue(snapshotJob("jc3"));
    const claimed = await client.claim(claimBody());
    expect(claimed.status).toBe(200);
    const jobId = claimed.json.job_id as string;
    const staleToken = (claimed.json.lease as { token: string }).token;
    await client.start(jobId, staleToken);

    await forceLeaseExpiry(jobId);

    const job = (await client.job(jobId)).json;
    expect(job.state).toBe("queued");
    expect(job.attempt).toBe(2);

    for (const call of [
      () => client.heartbeat(jobId, staleToken),
      () => client.fail(jobId, staleToken, { code: "internal", message: "x", retryable: true }),
      () => client.defer(jobId, staleToken, 60, { code: "quota" }),
      () => client.completeRaw(jobId, staleToken, "{}"),
    ]) {
      const { status, json } = await call();
      expect(status).toBe(409);
      expect(json.error).toBe("lease_lost");
    }

    // health surfaced (§5): expiry recorded
    const events = (await client.get(`/v1/health-events?job_id=${jobId}`)).json
      .events as Record<string, unknown>[];
    expect(events.some((e) => e.kind === "lease_expired")).toBe(true);

    // re-claimable by a second runner with the incremented attempt
    const reclaimed = await client.claim(claimBody({ runner_id: "runner-t2" }));
    expect(reclaimed.status).toBe(200);
    expect(reclaimed.json.job_id).toBe(jobId);
    expect(reclaimed.json.attempt).toBe(2);
  });

  it("exhausted attempts dead-letter with a health event", async () => {
    const { json } = await client.enqueue(snapshotJob("jc3-exhaust", { max_attempts: 2 }));
    const jobId = json.job_id as string;
    for (let round = 0; round < 2; round++) {
      const claimed = await client.claim(claimBody());
      expect(claimed.status).toBe(200);
      expect(claimed.json.job_id).toBe(jobId);
      await forceLeaseExpiry(jobId);
    }
    const job = (await client.job(jobId)).json;
    expect(job.state).toBe("dead_lettered");
    const events = (await client.get(`/v1/health-events?job_id=${jobId}`)).json
      .events as Record<string, unknown>[];
    expect(events.some((e) => e.kind === "attempts_exhausted")).toBe(true);
  });
});

describe("JC-5: defer honors not_before without consuming an attempt", () => {
  it("defers, stays unclaimable until due, attempt unchanged", async () => {
    await client.enqueue(snapshotJob("jc5"));
    const claimed = await client.claim(claimBody());
    const jobId = claimed.json.job_id as string;
    const token = (claimed.json.lease as { token: string }).token;
    await client.start(jobId, token);

    const deferred = await client.defer(jobId, token, 2, {
      code: "quota",
      message: "tokens exhausted",
    });
    expect(deferred.status).toBe(200);
    expect(deferred.json.status).toBe("deferred");

    const job = (await client.job(jobId)).json;
    expect(job.state).toBe("queued");
    expect(job.attempt).toBe(1);
    expect(job.deferrals).toBe(1);

    const early = await client.claim(claimBody());
    expect(early.status).toBe(204); // not_before still in the future

    await sleep(2200);
    const due = await client.claim(claimBody());
    expect(due.status).toBe(200);
    expect(due.json.job_id).toBe(jobId);
    expect(due.json.attempt).toBe(1);
  });

  it("deferral cap converts to a retryable failure with health", async () => {
    const { json } = await client.enqueue(snapshotJob("jc5-cap", { max_deferrals: 2 }));
    const jobId = json.job_id as string;
    for (let i = 0; i < 3; i++) {
      const claimed = await client.claim(claimBody());
      expect(claimed.status).toBe(200);
      const token = (claimed.json.lease as { token: string }).token;
      const result = await client.defer(jobId, token, 0, { code: "quota", message: "still" });
      if (i < 2) {
        expect(result.json.status).toBe("deferred");
      } else {
        expect(result.json.status).toBe("requeued"); // §5: converted to failure
      }
    }
    const job = (await client.job(jobId)).json;
    expect(job.state).toBe("queued");
    expect(job.attempt).toBe(2); // the conversion consumed an attempt
    expect(job.deferrals).toBe(2);
    const events = (await client.get(`/v1/health-events?job_id=${jobId}`)).json
      .events as Record<string, unknown>[];
    expect(events.some((e) => e.kind === "deferral_cap_reached")).toBe(true);
  });
});

describe("JC-6: invalid delivery → 422 → dead-letter (J-6)", () => {
  it("staged-invalid snapshot is rejected, nothing accepted", async () => {
    await client.enqueue(snapshotJob("jc6"));
    const claimed = await client.claim(claimBody());
    const jobId = claimed.json.job_id as string;
    const token = (claimed.json.lease as { token: string }).token;
    await client.start(jobId, token);

    const doc = JSON.parse(await demoSnapshot("jc6")) as {
      objects: { schema_hash: string }[];
    };
    doc.objects[0]!.schema_hash = `sha256:${"0".repeat(64)}`;
    const rejected = await client.completeRaw(jobId, token, JSON.stringify(doc));
    expect(rejected.status).toBe(422);
    expect(rejected.json.status).toBe("dead_lettered");
    expect(
      (rejected.json.errors as string[]).some((e) => e.includes("schema_hash mismatch")),
    ).toBe(true);

    const job = (await client.job(jobId)).json;
    expect(job.state).toBe("dead_lettered");
    expect((job.error as { code: string }).code).toBe("validation_error");

    const events = (await client.get(`/v1/health-events?job_id=${jobId}`)).json
      .events as Record<string, unknown>[];
    expect(events.some((e) => e.kind === "validation_rejected")).toBe(true);

    const snapshots = (await client.get(`/v1/snapshots?system=jc6`)).json
      .snapshots as unknown[];
    expect(snapshots).toHaveLength(0);

    // a retry of the same delivery is 409 — the lease died with the job
    const retry = await client.completeRaw(jobId, token, JSON.stringify(doc));
    expect(retry.status).toBe(409);
  });

  it("a system mismatch between job and snapshot is a validation failure", async () => {
    await client.enqueue(snapshotJob("jc6-sys"));
    const claimed = await client.claim(claimBody());
    const jobId = claimed.json.job_id as string;
    const token = (claimed.json.lease as { token: string }).token;
    const foreign = await demoSnapshot("some-other-system");
    const rejected = await client.completeRaw(jobId, token, foreign);
    expect(rejected.status).toBe(422);
    expect((await client.job(jobId)).json.state).toBe("dead_lettered");
  });
});

describe("JC-7: cancellation over heartbeat", () => {
  it("cancel_requested reaches the runner; cancelled fail is terminal", async () => {
    await client.enqueue(snapshotJob("jc7"));
    const claimed = await client.claim(claimBody());
    const jobId = claimed.json.job_id as string;
    const token = (claimed.json.lease as { token: string }).token;
    await client.start(jobId, token);

    const before = await client.heartbeat(jobId, token);
    expect(before.json.cancel_requested).toBe(false);

    const cancel = await client.cancel(jobId);
    expect(cancel.json.cancel_requested).toBe(true);

    const after = await client.heartbeat(jobId, token);
    expect(after.json.cancel_requested).toBe(true);

    const failed = await client.fail(jobId, token, {
      code: "cancelled",
      message: "cancelled by producer request",
      retryable: false,
    });
    expect(failed.json.status).toBe("cancelled");
    expect((await client.job(jobId)).json.state).toBe("cancelled");
  });

  it("cancelling a queued job is immediate", async () => {
    const { json } = await client.enqueue(snapshotJob("jc7-queued"));
    const cancelled = await client.cancel(json.job_id as string);
    expect(cancelled.json.state).toBe("cancelled");
    expect((await client.job(json.job_id as string)).json.state).toBe("cancelled");
  });
});

describe("JC-9: dedupe — one running + at most one queued per (system, type)", () => {
  it("absorbs an enqueue storm into one job + one follower", async () => {
    // N rapid enqueues while nothing runs → exactly one queued job.
    const first = await Promise.all(
      Array.from({ length: 8 }, () => client.enqueue(snapshotJob("jc9"))),
    );
    const ids = new Set(first.map((r) => r.json.job_id));
    expect(ids.size).toBe(1);
    const primary = [...ids][0] as string;

    // Lease it; a storm during execution yields exactly one follower.
    const claimed = await client.claim(claimBody());
    expect(claimed.json.job_id).toBe(primary);
    const followers = await Promise.all(
      Array.from({ length: 8 }, (_, i) =>
        client.enqueue(snapshotJob("jc9", { trigger: { kind: "webhook", detail: `ci-${i}` } })),
      ),
    );
    const followerIds = new Set(followers.map((r) => r.json.job_id));
    expect(followerIds.size).toBe(1);
    const followerId = [...followerIds][0] as string;
    expect(followerId).not.toBe(primary);

    const { rows } = await core.pool.query(
      `SELECT state, count(*) AS n FROM jobs WHERE system = 'jc9' GROUP BY state`,
    );
    const byState = Object.fromEntries(rows.map((r) => [r.state, Number(r.n)]));
    expect(byState).toEqual({ leased: 1, queued: 1 });

    // merged trigger history preserved on the follower
    const follower = (await client.job(followerId)).json;
    expect((follower.triggers as unknown[]).length).toBe(8);

    // the follower is not claimable while the primary holds the key
    const blocked = await client.claim(claimBody({ runner_id: "runner-t2" }));
    expect(blocked.status).toBe(204);

    // primary completes → follower becomes claimable
    const token = (claimed.json.lease as { token: string }).token;
    const delivered = await client.completeRaw(primary, token, await demoSnapshot("jc9"));
    expect(delivered.status).toBe(200);
    const next = await client.claim(claimBody({ runner_id: "runner-t2", wait_s: 3 }));
    expect(next.status).toBe(200);
    expect(next.json.job_id).toBe(followerId);
  });

  it("requeue with a queued follower absorbs the follower", async () => {
    const a = await client.enqueue(snapshotJob("jc9-absorb"));
    const claimed = await client.claim(claimBody());
    expect(claimed.json.job_id).toBe(a.json.job_id);
    const token = (claimed.json.lease as { token: string }).token;
    const b = await client.enqueue(snapshotJob("jc9-absorb"));
    expect(b.json.job_id).not.toBe(a.json.job_id);

    const failed = await client.fail(a.json.job_id as string, token, {
      code: "source_unavailable",
      message: "flaky",
      retryable: true,
    });
    expect(failed.json.status).toBe("requeued");

    const { rows } = await core.pool.query(
      `SELECT job_id, state, attempt, triggers FROM jobs WHERE system = 'jc9-absorb'`,
    );
    expect(rows).toHaveLength(1); // follower absorbed
    expect(rows[0].job_id).toBe(a.json.job_id);
    expect(rows[0].state).toBe("queued");
    expect(rows[0].attempt).toBe(2);
    const merged = rows[0].triggers as { merged_from?: string }[];
    expect(merged.some((t) => t.merged_from === b.json.job_id)).toBe(true);
  });
});

describe("snapshot acceptance (J-6 pass path)", () => {
  it("stores canonical bytes verbatim and records result_meta", async () => {
    await client.enqueue(snapshotJob("accept-ok"));
    const claimed = await client.claim(claimBody());
    const jobId = claimed.json.job_id as string;
    const token = (claimed.json.lease as { token: string }).token;
    await client.start(jobId, token);
    const bytes = await demoSnapshot("accept-ok");
    const done = await client.completeRaw(jobId, token, bytes);
    expect(done.status).toBe(200);
    expect(done.json.status).toBe("succeeded");

    const job = (await client.job(jobId)).json;
    expect(job.state).toBe("succeeded");
    const meta = job.result_meta as { snapshot_id: string; object_count: number };
    expect(meta.object_count).toBe(2);

    const stored = await client.get(`/v1/snapshots/${meta.snapshot_id}/body`);
    expect(stored.status).toBe(200);
    // byte-identity: stored body === what the CLI harness emitted
    const raw = await fetch(`${core.baseUrl}/v1/snapshots/${meta.snapshot_id}/body`, {
      headers: { authorization: `Bearer ${TEST_TOKEN}` },
    });
    expect(Buffer.from(await raw.arrayBuffer()).toString("utf-8")).toBe(bytes);
  });

  it("prunes to the retention limit per system (JP-3)", async () => {
    const bytes = await demoSnapshot("prune-sys");
    for (let i = 0; i < core.cfg.snapshotRetention + 3; i++) {
      await client.enqueue(snapshotJob("prune-sys"));
      const claimed = await client.claim(claimBody());
      const token = (claimed.json.lease as { token: string }).token;
      const done = await client.completeRaw(claimed.json.job_id as string, token, bytes);
      expect(done.status).toBe(200);
    }
    const snapshots = (await client.get(`/v1/snapshots?system=prune-sys&limit=100`)).json
      .snapshots as unknown[];
    expect(snapshots).toHaveLength(core.cfg.snapshotRetention);
  });
});
