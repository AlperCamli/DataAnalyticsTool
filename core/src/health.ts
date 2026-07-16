/**
 * Health events (job spec §5 dead-letter surfacing, §6.7 health column).
 * Minimal by ruling E1: a table the future dashboard reads, no UI.
 */

import pg from "pg";

export interface HealthEvent {
  kind: string;
  severity: "info" | "warning" | "error";
  system?: string | null;
  jobId?: string | null;
  detail?: Record<string, unknown>;
}

export async function recordHealthEvent(
  queryable: pg.Pool | pg.PoolClient,
  event: HealthEvent,
): Promise<void> {
  await queryable.query(
    `INSERT INTO health_events (kind, severity, system, job_id, detail)
     VALUES ($1, $2, $3, $4, $5::jsonb)`,
    [
      event.kind,
      event.severity,
      event.system ?? null,
      event.jobId ?? null,
      JSON.stringify(event.detail ?? {}),
    ],
  );
}

export async function listHealthEvents(
  pool: pg.Pool,
  filter: { system?: string; jobId?: string; limit?: number },
): Promise<Record<string, unknown>[]> {
  const clauses: string[] = [];
  const params: unknown[] = [];
  if (filter.system !== undefined) {
    params.push(filter.system);
    clauses.push(`system = $${params.length}`);
  }
  if (filter.jobId !== undefined) {
    params.push(filter.jobId);
    clauses.push(`job_id = $${params.length}`);
  }
  params.push(Math.min(filter.limit ?? 100, 500));
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const { rows } = await pool.query(
    `SELECT event_id, created_at, kind, severity, system, job_id, detail
       FROM health_events ${where}
      ORDER BY event_id DESC LIMIT $${params.length}`,
    params,
  );
  return rows;
}
