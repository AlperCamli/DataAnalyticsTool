/**
 * Freshness monitoring (sync spec §8, the OD-3 mechanism; SY-7).
 *
 * `computeFreshness` is the single definition of the computation — the
 * scheduler tick surfaces it as health events + `freshness_warnings`
 * rows, and the future MCP `report_freshness` tool (§6.9) imports the
 * same function. Age is measured mode-independently: a silently dead
 * schedule warns exactly like a stale manual source.
 */

import pg from "pg";
import { recordHealthEvent } from "./health.js";
import type { SyncPolicy, SystemPolicy } from "./policy.js";

export interface FreshnessReport {
  system: string;
  /** Seconds since captured_at of the latest accepted snapshot; null =
   * no accepted snapshot at all (warns unconditionally). */
  ageS: number | null;
  thresholdS: number;
  warning: boolean;
  /** Configured trigger mode, for the warning wording (SY-7). */
  mode: "schedule" | "webhook" | "manual";
  guidance: string;
}

function mode(policy: SystemPolicy): FreshnessReport["mode"] {
  if (policy.scheduleIntervalS !== null) return "schedule";
  if (policy.webhook) return "webhook";
  return "manual";
}

function guidance(policy: SystemPolicy, m: FreshnessReport["mode"]): string {
  switch (m) {
    case "schedule":
      return `scheduled every ${policy.scheduleIntervalS}s — check job health for failing snapshot jobs`;
    case "webhook":
      return "webhook-triggered — check that the CI hook is firing and check job health";
    default:
      return "manual-mode source — re-submit a snapshot (dashboard “sync now” / admin CLI, with fresh DDL files for case-A sources)";
  }
}

export async function computeFreshness(
  pool: pg.Pool,
  policy: SyncPolicy,
  now: Date = new Date(),
): Promise<FreshnessReport[]> {
  const reports: FreshnessReport[] = [];
  for (const [system, sp] of [...policy.systems.entries()].sort()) {
    const { rows } = await pool.query<{ captured_at: Date }>(
      `SELECT captured_at FROM accepted_snapshots
        WHERE system = $1 ORDER BY accepted_at DESC, snapshot_id DESC LIMIT 1`,
      [system],
    );
    const capturedAt = rows[0]?.captured_at ?? null;
    const ageS = capturedAt
      ? Math.max(0, (now.getTime() - capturedAt.getTime()) / 1000)
      : null;
    const m = mode(sp);
    reports.push({
      system,
      ageS,
      thresholdS: sp.freshnessThresholdS,
      warning: ageS === null || ageS > sp.freshnessThresholdS,
      mode: m,
      guidance: guidance(sp, m),
    });
  }
  return reports;
}

/**
 * Reconcile the warning state table with a fresh computation: raise on
 * crossing (health `freshness_warning`), clear when a newly accepted
 * snapshot brings age back under threshold (`freshness_cleared`).
 */
export async function applyFreshness(
  pool: pg.Pool,
  reports: FreshnessReport[],
): Promise<void> {
  const { rows } = await pool.query<{ system: string }>(
    `SELECT system FROM freshness_warnings`,
  );
  const active = new Set(rows.map((r) => r.system));
  for (const report of reports) {
    const detail = {
      age_s: report.ageS,
      threshold_s: report.thresholdS,
      trigger_mode: report.mode,
      guidance: report.guidance,
    };
    if (report.warning && !active.has(report.system)) {
      await pool.query(
        `INSERT INTO freshness_warnings (system, age_s, threshold_s, detail)
         VALUES ($1, $2, $3, $4::jsonb)`,
        [report.system, Math.round(report.ageS ?? -1), report.thresholdS, JSON.stringify(detail)],
      );
      await recordHealthEvent(pool, {
        kind: "freshness_warning",
        severity: "warning",
        system: report.system,
        detail,
      });
    } else if (!report.warning && active.has(report.system)) {
      await pool.query(`DELETE FROM freshness_warnings WHERE system = $1`, [
        report.system,
      ]);
      await recordHealthEvent(pool, {
        kind: "freshness_cleared",
        severity: "info",
        system: report.system,
        detail,
      });
    } else if (report.warning) {
      await pool.query(
        `UPDATE freshness_warnings
            SET age_s = $2, threshold_s = $3, detail = $4::jsonb
          WHERE system = $1`,
        [report.system, Math.round(report.ageS ?? -1), report.thresholdS, JSON.stringify(detail)],
      );
    }
  }
}
