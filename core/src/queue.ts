/**
 * The Postgres-backed job queue (job spec §4–§5, §8). Everything here is
 * core-internal (J-1): only the wire behavior in server.ts is normative.
 *
 * Concurrency model:
 * - claims are `SELECT … FOR UPDATE SKIP LOCKED` inside a transaction —
 *   at most one live lease per job (JC-2) — woken by LISTEN/NOTIFY;
 * - §8 dedupe is structural: a partial unique index caps queued batch
 *   jobs at one per (system, type), and the claim query refuses keys
 *   that already have a leased/running batch job, so "one running + at
 *   most one queued" holds under any interleaving;
 * - when a leased job must requeue (retryable failure, lease expiry)
 *   while a follower is already queued behind it, the follower is
 *   *absorbed*: its trigger history merges into the retrying job (both
 *   describe identical work — snapshots are absolute states) and the
 *   follower row is deleted, preserving the retrying job's attempt
 *   count and backoff so persistent failures still dead-letter.
 */

import pg from "pg";
import semver from "semver";
import type { CoreConfig } from "./config.js";
import { notifyJobs, withTransaction } from "./db.js";
import { recordHealthEvent } from "./health.js";
import { CLASS_DEFAULTS, JOB_TYPES, TRIGGER_KINDS } from "./registry.js";
import { ulid } from "./ulid.js";

export interface JobRow {
  job_id: string;
  type: string;
  class: "batch" | "interactive";
  system: string;
  connector_name: string;
  version_constraint: string;
  payload: { config?: Record<string, unknown>; credentials?: unknown[] };
  priority: number;
  attempt: number;
  max_attempts: number;
  deadline_s: number;
  state: string;
  not_before: Date;
  deferrals: number;
  max_deferrals: number;
  lease_token: string | null;
  lease_expires_at: Date | null;
  runner_id: string | null;
  cancel_requested: boolean;
  triggers: Record<string, unknown>[];
  progress: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  result: unknown;
  result_meta: Record<string, unknown> | null;
  created_at: Date;
  updated_at: Date;
  started_at: Date | null;
  finished_at: Date | null;
}

export interface ErrorEnvelope {
  code: string;
  message: string;
  retryable: boolean;
  detail?: Record<string, unknown>;
}

export class EnqueueError extends Error {
  constructor(readonly problems: string[]) {
    super(problems.join("; "));
  }
}

/** §4.1 job record as serialized over the wire (additive extras allowed). */
export function toWireRecord(row: JobRow): Record<string, unknown> {
  return {
    job_id: row.job_id,
    type: row.type,
    class: row.class,
    system: row.system,
    connector: { name: row.connector_name, version_constraint: row.version_constraint },
    payload: row.payload,
    priority: row.priority,
    attempt: row.attempt,
    max_attempts: row.max_attempts,
    deadline_s: row.deadline_s,
    created_at: row.created_at.toISOString(),
    trigger: row.triggers[0] ?? null,
    // additive fields (§9): observability for producers/ops
    triggers: row.triggers,
    state: row.state,
    deferrals: row.deferrals,
    cancel_requested: row.cancel_requested,
    runner_id: row.runner_id,
    progress: row.progress,
    error: row.error,
    result_meta: row.result_meta,
    not_before: row.not_before.toISOString(),
    started_at: row.started_at?.toISOString() ?? null,
    finished_at: row.finished_at?.toISOString() ?? null,
  };
}

// ---------------------------------------------------------------------------
// Enqueue (§8 dedupe)

export interface EnqueueRequest {
  type?: unknown;
  system?: unknown;
  connector?: { name?: unknown; version_constraint?: unknown };
  payload?: unknown;
  priority?: unknown;
  max_attempts?: unknown;
  deadline_s?: unknown;
  max_deferrals?: unknown;
  trigger?: { kind?: unknown; detail?: unknown };
}

function validateEnqueue(req: EnqueueRequest, cfg: CoreConfig) {
  const problems: string[] = [];
  const spec = typeof req.type === "string" ? JOB_TYPES.get(req.type) : undefined;
  if (!spec) {
    problems.push(`type must be one of: ${[...JOB_TYPES.keys()].join(", ")}`);
  }
  if (typeof req.system !== "string" || !req.system) {
    problems.push("system (non-empty string) is required");
  }
  const connectorName = req.connector?.name;
  if (typeof connectorName !== "string" || !connectorName) {
    problems.push("connector.name (non-empty string) is required");
  }
  const constraint =
    req.connector?.version_constraint === undefined ? "*" : req.connector.version_constraint;
  if (typeof constraint !== "string" || semver.validRange(constraint) === null) {
    problems.push(`connector.version_constraint is not a valid semver range`);
  }
  const trigger = req.trigger ?? { kind: "manual" };
  if (
    typeof trigger.kind !== "string" ||
    !(TRIGGER_KINDS as readonly string[]).includes(trigger.kind)
  ) {
    problems.push(`trigger.kind must be one of: ${TRIGGER_KINDS.join(", ")}`);
  }
  const payload = req.payload ?? {};
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    problems.push("payload must be an object");
  }
  for (const field of ["priority", "max_attempts", "deadline_s", "max_deferrals"] as const) {
    const value = req[field];
    if (value !== undefined && (!Number.isInteger(value) || (value as number) <= 0)) {
      problems.push(`${field} must be a positive integer`);
    }
  }
  if (problems.length > 0) throw new EnqueueError(problems);

  const defaults = CLASS_DEFAULTS[spec!.class];
  return {
    spec: spec!,
    system: req.system as string,
    connectorName: connectorName as string,
    constraint: constraint as string,
    payload: payload as Record<string, unknown>,
    priority: (req.priority as number | undefined) ?? defaults.priority,
    maxAttempts: (req.max_attempts as number | undefined) ?? defaults.maxAttempts,
    deadlineS: (req.deadline_s as number | undefined) ?? defaults.deadlineS,
    maxDeferrals: (req.max_deferrals as number | undefined) ?? cfg.maxDeferrals,
    trigger: {
      kind: trigger.kind as string,
      ...(trigger.detail !== undefined ? { detail: trigger.detail } : {}),
      at: new Date().toISOString(),
    },
  };
}

export async function enqueue(
  pool: pg.Pool,
  cfg: CoreConfig,
  req: EnqueueRequest,
): Promise<{ jobId: string; merged: boolean }> {
  const v = validateEnqueue(req, cfg);
  const jobId = ulid();
  const params = [
    jobId,
    v.spec.type,
    v.spec.class,
    v.system,
    v.connectorName,
    v.constraint,
    JSON.stringify(v.payload),
    v.priority,
    v.maxAttempts,
    v.deadlineS,
    v.maxDeferrals,
    JSON.stringify([v.trigger]),
  ];
  const insert = `
    INSERT INTO jobs (job_id, type, class, system, connector_name, version_constraint,
                      payload, priority, max_attempts, deadline_s, max_deferrals,
                      state, triggers)
    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, 'queued', $12::jsonb)`;
  let result: { jobId: string; merged: boolean };
  if (v.spec.class === "batch") {
    // §8: merge into the existing queued job for this (system, type);
    // the later trigger lands in its history. The partial unique index
    // is the arbiter, so a racing enqueue can never create two queued.
    const { rows } = await pool.query<{ job_id: string; inserted: boolean }>(
      `${insert}
       ON CONFLICT (system, type) WHERE state = 'queued' AND class = 'batch'
       DO UPDATE SET triggers = jobs.triggers || excluded.triggers, updated_at = now()
       RETURNING job_id, (xmax = 0) AS inserted`,
      params,
    );
    result = { jobId: rows[0]!.job_id, merged: !rows[0]!.inserted };
  } else {
    await pool.query(insert, params);
    result = { jobId, merged: false };
  }
  await notifyJobs(pool);
  return result;
}

// ---------------------------------------------------------------------------
// Claim (§6.1)

export interface ClaimDeclaration {
  name: string;
  version: string;
  /** Additive protocol field: job types the runner can execute for this
   * connector; absent means "no type filter" (pre-CP-3a clients). */
  types?: string[];
}

function matches(row: JobRow, connectors: ClaimDeclaration[]): boolean {
  return connectors.some(
    (d) =>
      d.name === row.connector_name &&
      typeof d.version === "string" &&
      semver.satisfies(d.version, row.version_constraint, { includePrerelease: true }) &&
      (d.types === undefined || d.types.includes(row.type)),
  );
}

export interface Lease {
  token: string;
  expires_at: string;
  ttl_s: number;
}

export async function claimOnce(
  pool: pg.Pool,
  cfg: CoreConfig,
  args: { runnerId: string; connectors: ClaimDeclaration[]; classes: string[] },
): Promise<{ row: JobRow; lease: Lease } | null> {
  const names = [...new Set(args.connectors.map((d) => d.name))];
  if (names.length === 0 || args.classes.length === 0) return null;
  return withTransaction(pool, async (client) => {
    const { rows } = await client.query<JobRow>(
      `SELECT * FROM jobs j
        WHERE j.state = 'queued'
          AND j.not_before <= now()
          AND j.class = ANY($1)
          AND j.connector_name = ANY($2)
          AND NOT EXISTS (
            SELECT 1 FROM jobs r
             WHERE r.system = j.system AND r.type = j.type
               AND r.class = 'batch' AND r.state IN ('leased', 'running'))
        ORDER BY j.priority, j.created_at
        LIMIT 16
        FOR UPDATE OF j SKIP LOCKED`,
      [args.classes, names],
    );
    const row = rows.find((r) => matches(r, args.connectors));
    if (!row) return null;
    const token = ulid() + ulid(); // opaque; uniqueness is what matters
    const { rows: updated } = await client.query<JobRow>(
      `UPDATE jobs
          SET state = 'leased', lease_token = $2, runner_id = $3,
              lease_expires_at = now() + make_interval(secs => $4),
              updated_at = now()
        WHERE job_id = $1
        RETURNING *`,
      [row.job_id, token, args.runnerId, cfg.leaseTtlS],
    );
    const granted = updated[0]!;
    return {
      row: granted,
      lease: {
        token,
        expires_at: granted.lease_expires_at!.toISOString(),
        ttl_s: cfg.leaseTtlS,
      },
    };
  });
}

// ---------------------------------------------------------------------------
// Lease-holder calls (§6.2–§6.6). All verify the lease first; a stale
// token is 409 lease_lost at the wire (null return here).

async function lockLeased(
  client: pg.PoolClient,
  jobId: string,
  leaseToken: string,
): Promise<JobRow | null> {
  const { rows } = await client.query<JobRow>(
    `SELECT * FROM jobs
      WHERE job_id = $1 AND lease_token = $2 AND state IN ('leased', 'running')
      FOR UPDATE`,
    [jobId, leaseToken],
  );
  return rows[0] ?? null;
}

export async function startJob(
  pool: pg.Pool,
  cfg: CoreConfig,
  jobId: string,
  leaseToken: string,
): Promise<{ cancelRequested: boolean } | null> {
  return withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return null;
    await client.query(
      `UPDATE jobs
          SET state = 'running', started_at = COALESCE(started_at, now()),
              lease_expires_at = now() + make_interval(secs => $2),
              updated_at = now()
        WHERE job_id = $1`,
      [jobId, cfg.leaseTtlS],
    );
    return { cancelRequested: row.cancel_requested };
  });
}

export async function heartbeatJob(
  pool: pg.Pool,
  cfg: CoreConfig,
  jobId: string,
  leaseToken: string,
  progress: Record<string, unknown> | undefined,
): Promise<{ lease: Lease; cancelRequested: boolean } | null> {
  return withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return null;
    // Each beat extends by one TTL (§5), but never past started_at +
    // deadline_s: past the deadline the lease lapses and the sweeper
    // requeues — deadline enforcement derived from the lease machinery.
    const { rows } = await client.query<{ lease_expires_at: Date }>(
      `UPDATE jobs
          SET lease_expires_at = LEAST(
                now() + make_interval(secs => $2),
                COALESCE(started_at + make_interval(secs => deadline_s),
                         now() + make_interval(secs => $2))),
              progress = COALESCE($3::jsonb, progress),
              updated_at = now()
        WHERE job_id = $1
        RETURNING lease_expires_at`,
      [jobId, cfg.leaseTtlS, progress === undefined ? null : JSON.stringify(progress)],
    );
    return {
      lease: {
        token: leaseToken,
        expires_at: rows[0]!.lease_expires_at.toISOString(),
        ttl_s: cfg.leaseTtlS,
      },
      cancelRequested: row.cancel_requested,
    };
  });
}

// ---------------------------------------------------------------------------
// Requeue / dead-letter plumbing

function backoffSeconds(cfg: CoreConfig, failedAttempt: number): number {
  const raw = Math.min(cfg.retryBaseS * 2 ** (failedAttempt - 1), cfg.retryCapS);
  const jitter = 0.8 + 0.4 * Math.random(); // ±20% (§5)
  return raw * jitter;
}

async function deadLetter(
  client: pg.PoolClient,
  row: JobRow,
  error: ErrorEnvelope,
  healthKind: string,
): Promise<void> {
  await client.query(
    `UPDATE jobs
        SET state = 'dead_lettered', error = $2::jsonb, finished_at = now(),
            lease_token = NULL, lease_expires_at = NULL, updated_at = now()
      WHERE job_id = $1`,
    [row.job_id, JSON.stringify(error)],
  );
  await recordHealthEvent(client, {
    kind: healthKind,
    severity: "error",
    system: row.system,
    jobId: row.job_id,
    detail: { error, attempt: row.attempt, max_attempts: row.max_attempts, type: row.type },
  });
}

async function cancelTerminal(client: pg.PoolClient, row: JobRow, error: ErrorEnvelope) {
  await client.query(
    `UPDATE jobs
        SET state = 'cancelled', error = $2::jsonb, finished_at = now(),
            lease_token = NULL, lease_expires_at = NULL, updated_at = now()
      WHERE job_id = $1`,
    [row.job_id, JSON.stringify(error)],
  );
}

/**
 * Retryable failure or lease expiry: requeue with backoff and attempt+1,
 * or dead-letter when attempts are exhausted (§5). Absorbs a queued
 * follower (see module docstring) so the requeue can never violate the
 * §8 single-queued invariant.
 */
async function requeueOrDeadLetter(
  client: pg.PoolClient,
  cfg: CoreConfig,
  row: JobRow,
  error: ErrorEnvelope,
  healthKind: string,
): Promise<"requeued" | "dead_lettered" | "cancelled"> {
  if (row.cancel_requested) {
    await cancelTerminal(client, row, {
      code: "cancelled",
      message: "cancel requested; job not retried",
      retryable: false,
    });
    return "cancelled";
  }
  if (row.attempt >= row.max_attempts) {
    await deadLetter(client, row, error, healthKind);
    return "dead_lettered";
  }
  let triggers = row.triggers;
  if (row.class === "batch") {
    const { rows: followers } = await client.query<JobRow>(
      `SELECT * FROM jobs
        WHERE system = $1 AND type = $2 AND class = 'batch' AND state = 'queued'
          AND job_id <> $3
        FOR UPDATE`,
      [row.system, row.type, row.job_id],
    );
    const follower = followers[0];
    if (follower) {
      await client.query(`DELETE FROM jobs WHERE job_id = $1`, [follower.job_id]);
      triggers = [
        ...triggers,
        ...follower.triggers.map((t) => ({ ...t, merged_from: follower.job_id })),
      ];
    }
  }
  const delayS = backoffSeconds(cfg, row.attempt);
  await client.query(
    `UPDATE jobs
        SET state = 'queued', attempt = attempt + 1,
            not_before = now() + make_interval(secs => $2),
            triggers = $3::jsonb, error = $4::jsonb,
            lease_token = NULL, lease_expires_at = NULL, runner_id = NULL,
            progress = NULL, updated_at = now()
      WHERE job_id = $1`,
    [row.job_id, delayS, JSON.stringify(triggers), JSON.stringify(error)],
  );
  return "requeued";
}

// ---------------------------------------------------------------------------
// Terminal wire calls

export type FailOutcome = "dead_lettered" | "requeued" | "cancelled" | null;

export async function failJob(
  pool: pg.Pool,
  cfg: CoreConfig,
  jobId: string,
  leaseToken: string,
  error: ErrorEnvelope,
): Promise<FailOutcome> {
  const outcome = await withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return null;
    if (error.code === "cancelled") {
      await cancelTerminal(client, row, error);
      await recordHealthEvent(client, {
        kind: "job_cancelled",
        severity: "info",
        system: row.system,
        jobId: row.job_id,
        detail: { type: row.type },
      });
      return "cancelled" as const;
    }
    if (!error.retryable) {
      await deadLetter(client, row, error, "job_dead_lettered");
      return "dead_lettered" as const;
    }
    return requeueOrDeadLetter(client, cfg, row, error, "attempts_exhausted");
  });
  if (outcome === "requeued") await notifyJobs(pool);
  return outcome;
}

export async function deferJob(
  pool: pg.Pool,
  cfg: CoreConfig,
  jobId: string,
  leaseToken: string,
  retryAfterS: number,
  reason: { code?: string; message?: string },
): Promise<"deferred" | "requeued" | "dead_lettered" | "cancelled" | null> {
  const outcome = await withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return null;
    if (row.cancel_requested) {
      await cancelTerminal(client, row, {
        code: "cancelled",
        message: "cancel requested; deferral not honored",
        retryable: false,
      });
      return "cancelled" as const;
    }
    if (row.deferrals + 1 > row.max_deferrals) {
      // §5: past the cap, deferrals become retryable failures so a
      // stuck quota surfaces in health instead of deferring forever.
      await recordHealthEvent(client, {
        kind: "deferral_cap_reached",
        severity: "warning",
        system: row.system,
        jobId: row.job_id,
        detail: { max_deferrals: row.max_deferrals, reason },
      });
      return requeueOrDeadLetter(
        client,
        cfg,
        row,
        {
          code: typeof reason.code === "string" ? reason.code : "quota",
          message: `deferral cap (${row.max_deferrals}) reached: ${reason.message ?? ""}`,
          retryable: true,
        },
        "attempts_exhausted",
      );
    }
    await client.query(
      `UPDATE jobs
          SET state = 'queued', not_before = now() + make_interval(secs => $2),
              deferrals = deferrals + 1,
              error = $3::jsonb,
              lease_token = NULL, lease_expires_at = NULL, runner_id = NULL,
              progress = NULL, updated_at = now()
        WHERE job_id = $1`,
      [
        jobId,
        retryAfterS,
        JSON.stringify({ ...reason, via: "defer", retryable: true }),
      ],
    );
    return "deferred" as const;
  });
  if (outcome === "requeued") await notifyJobs(pool);
  return outcome;
}

/** Snapshot delivery accepted (J-6 passed): store + prune + succeed. */
export async function succeedSnapshot(
  pool: pg.Pool,
  cfg: CoreConfig,
  jobId: string,
  leaseToken: string,
  verdict: {
    system: string;
    snapshot_version: string;
    source_mode: string;
    captured_at: string;
    connector: { name: string; version: string };
    object_count: number;
    sha256: string;
    canonical_body_sha256: string;
  },
  body: Buffer,
): Promise<{ snapshotId: string } | null> {
  const result = await withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return null;
    const snapshotId = ulid();
    await client.query(
      `INSERT INTO accepted_snapshots
         (snapshot_id, system, job_id, snapshot_version, source_mode,
          connector_name, connector_version, captured_at, body, sha256,
          canonical_body_sha256, object_count)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)`,
      [
        snapshotId,
        row.system,
        row.job_id,
        verdict.snapshot_version,
        verdict.source_mode,
        verdict.connector.name,
        verdict.connector.version,
        verdict.captured_at,
        body,
        verdict.sha256,
        verdict.canonical_body_sha256,
        verdict.object_count,
      ],
    );
    // JP-3 retention: keep the newest N per system.
    await client.query(
      `DELETE FROM accepted_snapshots
        WHERE system = $1
          AND snapshot_id NOT IN (
            SELECT snapshot_id FROM accepted_snapshots
             WHERE system = $1
             ORDER BY accepted_at DESC, snapshot_id DESC
             LIMIT $2)`,
      [row.system, cfg.snapshotRetention],
    );
    await client.query(
      `UPDATE jobs
          SET state = 'succeeded', finished_at = now(),
              result_meta = $2::jsonb,
              lease_token = NULL, lease_expires_at = NULL, updated_at = now()
        WHERE job_id = $1`,
      [
        jobId,
        JSON.stringify({
          snapshot_id: snapshotId,
          sha256: verdict.sha256,
          canonical_body_sha256: verdict.canonical_body_sha256,
          object_count: verdict.object_count,
        }),
      ],
    );
    return { snapshotId };
  });
  // A queued follower for this key may be claimable now.
  if (result) await notifyJobs(pool);
  return result;
}

/** J-6 validation failed: dead-letter with `validation_error` (§6.4). */
export async function rejectDelivery(
  pool: pg.Pool,
  jobId: string,
  leaseToken: string,
  errors: string[],
): Promise<boolean> {
  const done = await withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return false;
    await deadLetter(
      client,
      row,
      {
        code: "validation_error",
        message: "core rejected delivered result (J-6)",
        retryable: false,
        detail: { errors },
      },
      "validation_rejected",
    );
    return true;
  });
  if (done) await notifyJobs(pool);
  return done;
}

/** Non-snapshot completion: store the result envelope inline (§6.4). */
export async function succeedInline(
  pool: pg.Pool,
  jobId: string,
  leaseToken: string,
  result: unknown,
): Promise<boolean> {
  const done = await withTransaction(pool, async (client) => {
    const row = await lockLeased(client, jobId, leaseToken);
    if (!row) return false;
    await client.query(
      `UPDATE jobs
          SET state = 'succeeded', finished_at = now(), result = $2::jsonb,
              lease_token = NULL, lease_expires_at = NULL, updated_at = now()
        WHERE job_id = $1`,
      [jobId, JSON.stringify(result ?? null)],
    );
    return true;
  });
  if (done) await notifyJobs(pool);
  return done;
}

// ---------------------------------------------------------------------------
// Producer-side operations

export async function cancelJob(
  pool: pg.Pool,
  jobId: string,
): Promise<{ state: string; cancelRequested: boolean } | null> {
  return withTransaction(pool, async (client) => {
    const { rows } = await client.query<JobRow>(
      `SELECT * FROM jobs WHERE job_id = $1 FOR UPDATE`,
      [jobId],
    );
    const row = rows[0];
    if (!row) return null;
    if (row.state === "queued") {
      await cancelTerminal(client, row, {
        code: "cancelled",
        message: "cancelled while queued",
        retryable: false,
      });
      return { state: "cancelled", cancelRequested: false };
    }
    if (row.state === "leased" || row.state === "running") {
      await client.query(
        `UPDATE jobs SET cancel_requested = true, updated_at = now() WHERE job_id = $1`,
        [jobId],
      );
      return { state: row.state, cancelRequested: true };
    }
    return { state: row.state, cancelRequested: row.cancel_requested };
  });
}

export async function getJob(pool: pg.Pool, jobId: string): Promise<JobRow | null> {
  const { rows } = await pool.query<JobRow>(`SELECT * FROM jobs WHERE job_id = $1`, [jobId]);
  return rows[0] ?? null;
}

export async function listJobs(
  pool: pg.Pool,
  filter: { state?: string; system?: string; type?: string; limit?: number },
): Promise<JobRow[]> {
  const clauses: string[] = [];
  const params: unknown[] = [];
  for (const [column, value] of [
    ["state", filter.state],
    ["system", filter.system],
    ["type", filter.type],
  ] as const) {
    if (value !== undefined) {
      params.push(value);
      clauses.push(`${column} = $${params.length}`);
    }
  }
  params.push(Math.min(filter.limit ?? 100, 500));
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const { rows } = await pool.query<JobRow>(
    `SELECT * FROM jobs ${where} ORDER BY created_at DESC LIMIT $${params.length}`,
    params,
  );
  return rows;
}

// ---------------------------------------------------------------------------
// Lease-expiry sweep (§4.3 core-side event)

export async function sweepExpiredLeases(
  pool: pg.Pool,
  cfg: CoreConfig,
): Promise<number> {
  const swept = await withTransaction(pool, async (client) => {
    const { rows } = await client.query<JobRow>(
      `SELECT * FROM jobs
        WHERE state IN ('leased', 'running') AND lease_expires_at < now()
        FOR UPDATE SKIP LOCKED`,
    );
    for (const row of rows) {
      await recordHealthEvent(client, {
        kind: "lease_expired",
        severity: "warning",
        system: row.system,
        jobId: row.job_id,
        detail: { runner_id: row.runner_id, attempt: row.attempt, type: row.type },
      });
      await requeueOrDeadLetter(
        client,
        cfg,
        row,
        {
          code: "internal",
          message: "lease expired (missed heartbeats) — treated as internal (§6.7)",
          retryable: true,
        },
        "attempts_exhausted",
      );
    }
    return rows.length;
  });
  if (swept > 0) await notifyJobs(pool);
  return swept;
}
