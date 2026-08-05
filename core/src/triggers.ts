/**
 * Trigger ingestion (sync spec §4): all three trigger kinds reduce to
 * the same effect — enqueue a `snapshot` job for the system (job §4.1
 * `trigger.kind` records provenance) and mark it trigger-pending for
 * the next run (§7 coalescing). The connection registry (`sync_systems`)
 * supplies the job template; job-protocol dedupe absorbs storms.
 */

import pg from "pg";
import type { CoreConfig } from "./config.js";
import { notifySync } from "./db.js";
import { enqueue } from "./queue.js";

export interface SyncSystem {
  system: string;
  connector_name: string;
  version_constraint: string;
  payload: Record<string, unknown>;
}

export async function getSyncSystem(
  pool: pg.Pool,
  system: string,
): Promise<SyncSystem | null> {
  const { rows } = await pool.query<SyncSystem>(
    `SELECT system, connector_name, version_constraint, payload
       FROM sync_systems WHERE system = $1`,
    [system],
  );
  return rows[0] ?? null;
}

export async function listSyncSystems(pool: pg.Pool): Promise<SyncSystem[]> {
  const { rows } = await pool.query<SyncSystem & { updated_at: Date }>(
    `SELECT system, connector_name, version_constraint, payload, updated_at
       FROM sync_systems ORDER BY system`,
  );
  return rows;
}

/**
 * A write this store did not take (D-84's class).
 *
 * Thrown when the row read back after a write is not the row that was
 * written. Callers must not translate this into a success of any kind:
 * the whole point is that "registered" stops being something the writer
 * asserts and becomes something the store demonstrates.
 */
export class RegistryWriteNotObserved extends Error {
  constructor(readonly system: string, readonly detail: string) {
    super(`connection ${system}: ${detail}`);
  }
}

/** Canonical JSON for the comparison: key order must not decide equality. */
function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([k, v]) => `${JSON.stringify(k)}:${stableJson(v)}`)
    .join(",")}}`;
}

/**
 * Register or update a connection, then **read it back and prove it**.
 *
 * A-3's structural gate. The D-84 pair — a connection reported
 * registered that was absent, a drift PR reported opened that was never
 * opened — cost two silent days, and both had the same shape: the
 * writer described its own intent and nobody asked the store. So this
 * function does not return what it wrote. It writes, re-reads through
 * the ordinary read path, compares, and throws when the store disagrees.
 * A caller cannot report success on a write that did not land, because
 * the only value it has to report with is the one the store just handed
 * back.
 *
 * Every writer goes through here, tests included: a verification only
 * the production path performs is a verification the next writer will
 * skip.
 */
export async function upsertSyncSystem(pool: pg.Pool, s: SyncSystem): Promise<SyncSystem> {
  await pool.query(
    `INSERT INTO sync_systems (system, connector_name, version_constraint, payload)
     VALUES ($1, $2, $3, $4::jsonb)
     ON CONFLICT (system) DO UPDATE
        SET connector_name = excluded.connector_name,
            version_constraint = excluded.version_constraint,
            payload = excluded.payload,
            updated_at = now()`,
    [s.system, s.connector_name, s.version_constraint, JSON.stringify(s.payload)],
  );
  const stored = await getSyncSystem(pool, s.system);
  if (!stored) {
    throw new RegistryWriteNotObserved(
      s.system,
      "the write reported no error and the row is not in the store — refusing to report it registered",
    );
  }
  const differs =
    stored.connector_name !== s.connector_name ||
    stored.version_constraint !== s.version_constraint ||
    stableJson(stored.payload) !== stableJson(s.payload);
  if (differs) {
    throw new RegistryWriteNotObserved(
      s.system,
      "the row read back after the write is not the row that was written",
    );
  }
  return stored;
}

/** Delete, then prove the absence — the deletion half of the same rule. */
export async function deleteSyncSystem(pool: pg.Pool, system: string): Promise<boolean> {
  const { rowCount } = await pool.query(`DELETE FROM sync_systems WHERE system = $1`, [system]);
  if (await getSyncSystem(pool, system)) {
    throw new RegistryWriteNotObserved(
      system,
      "the delete reported no error and the row is still in the store",
    );
  }
  return (rowCount ?? 0) > 0;
}

export interface TriggerRecord {
  kind: "schedule" | "webhook" | "manual";
  detail?: Record<string, unknown>;
  at: string;
}

/**
 * The one trigger effect (§4): enqueue + mark pending + wake the run
 * loop. Returns the job id (a merged enqueue returns the absorbing
 * queued job's id, which is exactly the job acquisition should await).
 */
export async function triggerSystem(
  pool: pg.Pool,
  cfg: CoreConfig,
  system: SyncSystem,
  trigger: { kind: TriggerRecord["kind"]; detail?: Record<string, unknown> },
): Promise<string> {
  const { jobId } = await enqueue(pool, cfg, {
    type: "snapshot",
    system: system.system,
    connector: {
      name: system.connector_name,
      version_constraint: system.version_constraint,
    },
    payload: system.payload,
    trigger,
  });
  const record: TriggerRecord = {
    kind: trigger.kind,
    ...(trigger.detail !== undefined ? { detail: trigger.detail } : {}),
    at: new Date().toISOString(),
  };
  await pool.query(
    `INSERT INTO sync_pending (system, triggers, job_id)
     VALUES ($1, $2::jsonb, $3)
     ON CONFLICT (system) DO UPDATE
        SET triggers = sync_pending.triggers || excluded.triggers,
            job_id = excluded.job_id,
            updated_at = now()`,
    [system.system, JSON.stringify([record]), jobId],
  );
  await notifySync(pool);
  return jobId;
}

export interface PendingSystem {
  system: string;
  triggers: TriggerRecord[];
  job_id: string | null;
}

/** Atomically consume every pending mark (run pin, §5.1). */
export async function consumePending(client: pg.PoolClient): Promise<PendingSystem[]> {
  const { rows } = await client.query<PendingSystem>(
    `DELETE FROM sync_pending RETURNING system, triggers, job_id`,
  );
  return rows.sort((a, b) => (a.system < b.system ? -1 : 1));
}

export async function hasPending(pool: pg.Pool): Promise<boolean> {
  const { rows } = await pool.query(`SELECT 1 FROM sync_pending LIMIT 1`);
  return rows.length > 0;
}

/** Re-mark systems pending (retry_head_moved → coalesced re-run, §5). */
export async function remarkPending(
  pool: pg.Pool,
  systems: PendingSystem[],
): Promise<void> {
  for (const s of systems) {
    await pool.query(
      `INSERT INTO sync_pending (system, triggers, job_id)
       VALUES ($1, $2::jsonb, $3)
       ON CONFLICT (system) DO UPDATE
          SET triggers = excluded.triggers || sync_pending.triggers,
              job_id = COALESCE(sync_pending.job_id, excluded.job_id),
              updated_at = now()`,
      [s.system, JSON.stringify(s.triggers), s.job_id],
    );
  }
  await notifySync(pool);
}

// ---------------------------------------------------------------------------
// Webhook secrets (§4.2, ruling E2)

export async function setHookSecret(
  pool: pg.Pool,
  system: string,
  secretHash: string,
): Promise<"created" | "rotated"> {
  const { rows } = await pool.query<{ inserted: boolean }>(
    `INSERT INTO sync_hooks (system, secret_hash)
     VALUES ($1, $2)
     ON CONFLICT (system) DO UPDATE
        SET secret_hash = excluded.secret_hash, rotated_at = now()
     RETURNING (xmax = 0) AS inserted`,
    [system, secretHash],
  );
  return rows[0]!.inserted ? "created" : "rotated";
}

export async function getHookSecretHash(
  pool: pg.Pool,
  system: string,
): Promise<string | null> {
  const { rows } = await pool.query<{ secret_hash: string }>(
    `SELECT secret_hash FROM sync_hooks WHERE system = $1`,
    [system],
  );
  return rows[0]?.secret_hash ?? null;
}
