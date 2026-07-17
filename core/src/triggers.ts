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

export async function upsertSyncSystem(pool: pg.Pool, s: SyncSystem): Promise<void> {
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
