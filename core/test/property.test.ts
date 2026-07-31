/**
 * Queue property tests (fast-check) against a real Postgres queue:
 *
 * 1. §8 dedupe invariant — under any interleaving of enqueues, claims,
 *    retryable/final failures, defers, and forced lease expiries, every
 *    (system, type) key holds ≤1 queued and ≤1 leased/running batch job.
 * 2. Lease expiry → reclaim, and max_attempts → dead-letter: a job that
 *    keeps losing its lease is claimable exactly max_attempts times and
 *    then dead-letters with a health event.
 */

import fc from "fast-check";
import { afterAll, beforeAll, expect, it } from "vitest";
import {
  claimOnce,
  enqueue,
  failJob,
  deferJob,
  getJob,
  sweepExpiredLeases,
} from "../src/queue.js";
import { startCore, type TestCore } from "./helpers.js";

let core: TestCore;
let namespace = 0;

beforeAll(async () => {
  core = await startCore();
});

afterAll(async () => {
  await core.stop();
});

interface ModelState {
  ns: string;
  /** live lease tokens: jobId → token */
  leases: Map<string, string>;
}

type Command =
  | { op: "enqueue"; key: number }
  | { op: "claim"; runner: number }
  | { op: "fail_retryable" }
  | { op: "fail_final" }
  | { op: "defer"; retryAfterS: number }
  | { op: "expire_and_sweep" };

const commandArb: fc.Arbitrary<Command> = fc.oneof(
  { weight: 4, arbitrary: fc.record({ op: fc.constant("enqueue" as const), key: fc.integer({ min: 0, max: 2 }) }) },
  { weight: 4, arbitrary: fc.record({ op: fc.constant("claim" as const), runner: fc.integer({ min: 0, max: 1 }) }) },
  { weight: 2, arbitrary: fc.constant({ op: "fail_retryable" as const }) },
  { weight: 1, arbitrary: fc.constant({ op: "fail_final" as const }) },
  { weight: 1, arbitrary: fc.record({ op: fc.constant("defer" as const), retryAfterS: fc.integer({ min: 0, max: 1 }) }) },
  { weight: 1, arbitrary: fc.constant({ op: "expire_and_sweep" as const }) },
);

async function apply(state: ModelState, command: Command): Promise<void> {
  switch (command.op) {
    case "enqueue": {
      await enqueue(core.pool, core.cfg, {
        type: "snapshot",
        system: `${state.ns}-s${command.key}`,
        connector: { name: `propconn-${state.ns}`, version_constraint: "*" },
        payload: {},
        trigger: { kind: "manual" },
      });
      return;
    }
    case "claim": {
      const claimed = await claimOnce(core.pool, core.cfg, {
        runnerId: `prop-r${command.runner}`,
        connectors: [{ name: `propconn-${state.ns}`, version: "1.0.0" }],
        classes: ["batch"],
      });
      if (claimed && claimed.row.system.startsWith(state.ns)) {
        state.leases.set(claimed.row.job_id, claimed.lease.token);
      }
      return;
    }
    case "fail_retryable":
    case "fail_final": {
      const entry = state.leases.entries().next();
      if (entry.done) return;
      const [jobId, token] = entry.value;
      state.leases.delete(jobId);
      await failJob(core.pool, core.cfg, jobId, token, {
        code: command.op === "fail_final" ? "config_error" : "source_unavailable",
        message: "staged",
        retryable: command.op === "fail_retryable",
      });
      return;
    }
    case "defer": {
      const entry = state.leases.entries().next();
      if (entry.done) return;
      const [jobId, token] = entry.value;
      state.leases.delete(jobId);
      await deferJob(core.pool, core.cfg, jobId, token, command.retryAfterS, {
        code: "quota",
        message: "staged",
      });
      return;
    }
    case "expire_and_sweep": {
      await core.pool.query(
        `UPDATE jobs SET lease_expires_at = now() - interval '1 second'
          WHERE state IN ('leased', 'running') AND system LIKE $1`,
        [`${state.ns}-%`],
      );
      state.leases.clear();
      await sweepExpiredLeases(core.pool, core.cfg);
      return;
    }
  }
}

it("dedupe invariant holds under arbitrary interleavings (§8)", async () => {
  await fc.assert(
    fc.asyncProperty(fc.array(commandArb, { maxLength: 25 }), async (commands) => {
      const state: ModelState = { ns: `p${namespace++}`, leases: new Map() };
      for (const command of commands) {
        await apply(state, command);
      }
      const { rows } = await core.pool.query<{
        system: string;
        queued: string;
        active: string;
      }>(
        `SELECT system,
                count(*) FILTER (WHERE state = 'queued') AS queued,
                count(*) FILTER (WHERE state IN ('leased', 'running')) AS active
           FROM jobs
          WHERE class = 'batch' AND system LIKE $1
          GROUP BY system, type`,
        [`${state.ns}-%`],
      );
      for (const row of rows) {
        expect(Number(row.queued), `${row.system}: >1 queued`).toBeLessThanOrEqual(1);
        expect(Number(row.active), `${row.system}: >1 active`).toBeLessThanOrEqual(1);
      }
      // attempts never exceed max_attempts
      const { rows: overs } = await core.pool.query(
        `SELECT job_id FROM jobs WHERE system LIKE $1 AND attempt > max_attempts`,
        [`${state.ns}-%`],
      );
      expect(overs).toHaveLength(0);
    }),
    { numRuns: 12 },
  );
}, 240_000);

it("defer absorbs a queued follower before requeueing the active batch", async () => {
  const system = `defer-follower-${namespace++}`;
  const connector = `conn-${system}`;
  const first = await enqueue(core.pool, core.cfg, {
    type: "snapshot",
    system,
    connector: { name: connector, version_constraint: "*" },
    payload: {},
    trigger: { kind: "manual", detail: { source: "first" } },
  });
  const claimed = await claimOnce(core.pool, core.cfg, {
    runnerId: "defer-follower-runner",
    connectors: [{ name: connector, version: "1.0.0" }],
    classes: ["batch"],
  });
  expect(claimed?.row.job_id).toBe(first.jobId);

  const follower = await enqueue(core.pool, core.cfg, {
    type: "snapshot",
    system,
    connector: { name: connector, version_constraint: "*" },
    payload: {},
    trigger: { kind: "manual", detail: { source: "follower" } },
  });
  expect(follower.jobId).not.toBe(first.jobId);

  const outcome = await deferJob(
    core.pool,
    core.cfg,
    first.jobId,
    claimed!.lease.token,
    0,
    { code: "quota", message: "staged" },
  );
  expect(outcome).toBe("deferred");

  const { rows } = await core.pool.query<{
    job_id: string;
    state: string;
    triggers: Array<{ merged_from?: string }>;
  }>(
    `SELECT job_id, state, triggers
       FROM jobs
      WHERE system = $1 AND type = 'snapshot'`,
    [system],
  );
  expect(rows).toHaveLength(1);
  expect(rows[0]!.job_id).toBe(first.jobId);
  expect(rows[0]!.state).toBe("queued");
  expect(rows[0]!.triggers).toHaveLength(2);
  expect(rows[0]!.triggers[1]!.merged_from).toBe(follower.jobId);
});

it("repeated lease expiry reclaims exactly max_attempts times, then dead-letters", async () => {
  await fc.assert(
    fc.asyncProperty(fc.integer({ min: 1, max: 4 }), async (maxAttempts) => {
      const system = `expiry-${namespace++}`;
      const { jobId } = await enqueue(core.pool, core.cfg, {
        type: "snapshot",
        system,
        connector: { name: `conn-${system}`, version_constraint: "*" },
        payload: {},
        max_attempts: maxAttempts,
        trigger: { kind: "manual" },
      });
      let claims = 0;
      for (let round = 0; round < maxAttempts + 3; round++) {
        const claimed = await claimOnce(core.pool, core.cfg, {
          runnerId: `expiry-r${round % 2}`, // alternating replicas
          connectors: [{ name: `conn-${system}`, version: "1.0.0" }],
          classes: ["batch"],
        });
        if (!claimed) break;
        expect(claimed.row.job_id).toBe(jobId);
        expect(claimed.row.attempt).toBe(claims + 1);
        claims += 1;
        await core.pool.query(
          `UPDATE jobs SET lease_expires_at = now() - interval '1 second' WHERE job_id = $1`,
          [jobId],
        );
        await sweepExpiredLeases(core.pool, core.cfg);
      }
      expect(claims).toBe(maxAttempts);
      const job = await getJob(core.pool, jobId);
      expect(job!.state).toBe("dead_lettered");
      const { rows: events } = await core.pool.query(
        `SELECT kind FROM health_events WHERE job_id = $1`,
        [jobId],
      );
      const kinds = events.map((e) => e.kind);
      expect(kinds).toContain("lease_expired");
      expect(kinds).toContain("attempts_exhausted");
    }),
    { numRuns: 8 },
  );
}, 240_000);

it("defers below the cap never consume an attempt; the cap converts (J-5/§5)", async () => {
  await fc.assert(
    fc.asyncProperty(fc.integer({ min: 1, max: 5 }), async (cap) => {
      const system = `defer-${namespace++}`;
      const { jobId } = await enqueue(core.pool, core.cfg, {
        type: "snapshot",
        system,
        connector: { name: `conn-${system}`, version_constraint: "*" },
        payload: {},
        max_deferrals: cap,
        trigger: { kind: "schedule", detail: "nightly" },
      });
      for (let i = 0; i < cap; i++) {
        const claimed = await claimOnce(core.pool, core.cfg, {
          runnerId: "defer-r",
          connectors: [{ name: `conn-${system}`, version: "1.0.0" }],
          classes: ["batch"],
        });
        expect(claimed).not.toBeNull();
        const outcome = await deferJob(
          core.pool,
          core.cfg,
          jobId,
          claimed!.lease.token,
          0,
          { code: "quota", message: "window" },
        );
        expect(outcome).toBe("deferred");
        const job = await getJob(core.pool, jobId);
        expect(job!.attempt).toBe(1);
        expect(job!.deferrals).toBe(i + 1);
      }
      const claimed = await claimOnce(core.pool, core.cfg, {
        runnerId: "defer-r",
        connectors: [{ name: `conn-${system}`, version: "1.0.0" }],
        classes: ["batch"],
      });
      const outcome = await deferJob(core.pool, core.cfg, jobId, claimed!.lease.token, 0, {
        code: "quota",
        message: "window",
      });
      expect(["requeued", "dead_lettered"]).toContain(outcome as string);
      const job = await getJob(core.pool, jobId);
      expect(job!.attempt + (job!.state === "dead_lettered" ? 1 : 0)).toBeGreaterThanOrEqual(2);
    }),
    { numRuns: 5 },
  );
}, 240_000);
