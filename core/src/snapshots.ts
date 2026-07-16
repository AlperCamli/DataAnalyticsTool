/**
 * Accepted-snapshot reads (the write path lives in queue.succeedSnapshot,
 * inside the delivery transaction). `body` is served as the stored
 * canonical bytes, never re-serialized.
 */

import pg from "pg";

export interface SnapshotMeta {
  snapshot_id: string;
  system: string;
  job_id: string | null;
  snapshot_version: string;
  source_mode: string;
  connector_name: string;
  connector_version: string;
  captured_at: Date;
  sha256: string;
  canonical_body_sha256: string;
  object_count: number;
  accepted_at: Date;
}

const META_COLUMNS = `snapshot_id, system, job_id, snapshot_version, source_mode,
  connector_name, connector_version, captured_at, sha256,
  canonical_body_sha256, object_count, accepted_at`;

export async function listSnapshots(
  pool: pg.Pool,
  filter: { system?: string; limit?: number },
): Promise<SnapshotMeta[]> {
  const params: unknown[] = [];
  let where = "";
  if (filter.system !== undefined) {
    params.push(filter.system);
    where = `WHERE system = $1`;
  }
  params.push(Math.min(filter.limit ?? 50, 200));
  const { rows } = await pool.query<SnapshotMeta>(
    `SELECT ${META_COLUMNS} FROM accepted_snapshots ${where}
      ORDER BY accepted_at DESC, snapshot_id DESC LIMIT $${params.length}`,
    params,
  );
  return rows;
}

export async function getSnapshotBody(
  pool: pg.Pool,
  snapshotId: string,
): Promise<Buffer | null> {
  const { rows } = await pool.query<{ body: Buffer }>(
    `SELECT body FROM accepted_snapshots WHERE snapshot_id = $1`,
    [snapshotId],
  );
  return rows[0]?.body ?? null;
}
