/**
 * Scheduler tick (sync spec §4.1) + freshness evaluation (§8).
 *
 * Coarse tick (default hourly): reads sync-policy.yaml from KB HEAD —
 * fresh every tick, no cache beyond it (E2), so a policy edit merged to
 * the KB takes effect on the next tick with no redeploy (SO-2) — then
 * (a) triggers a scheduled snapshot for every system whose latest
 * accepted snapshot is older than its interval, and (b) reconciles
 * freshness warnings. Job dedupe absorbs the re-trigger on every tick
 * while a snapshot job is already queued/running.
 */

import pg from "pg";
import type { CoreConfig } from "./config.js";
import { applyFreshness, computeFreshness } from "./freshness.js";
import { readRemoteFile } from "./gitkb.js";
import { recordHealthEvent } from "./health.js";
import { parsePolicy, type SyncPolicy } from "./policy.js";
import { getSyncSystem, triggerSystem } from "./triggers.js";

export const POLICY_PATH = ".contextlayer/sync-policy.yaml";

export async function readPolicyFromHead(cfg: CoreConfig): Promise<SyncPolicy> {
  const { text } = await readRemoteFile(cfg.sync, POLICY_PATH);
  return parsePolicy(text);
}

export interface TickResult {
  triggered: string[];
  policy: SyncPolicy;
}

export async function schedulerTick(
  pool: pg.Pool,
  cfg: CoreConfig,
  log: (msg: string) => void,
): Promise<TickResult> {
  const policy = await readPolicyFromHead(cfg);

  const triggered: string[] = [];
  for (const [system, sp] of [...policy.systems.entries()].sort()) {
    if (sp.scheduleIntervalS === null) continue;
    const { rows } = await pool.query<{ age_s: string | null }>(
      `SELECT EXTRACT(EPOCH FROM now() - max(captured_at)) AS age_s
         FROM accepted_snapshots WHERE system = $1`,
      [system],
    );
    const ageS = rows[0]?.age_s === null || rows[0] === undefined
      ? null
      : Number(rows[0].age_s);
    if (ageS !== null && ageS <= sp.scheduleIntervalS) continue;
    const registered = await getSyncSystem(pool, system);
    if (!registered) {
      await recordHealthEvent(pool, {
        kind: "sync_system_unregistered",
        severity: "warning",
        system,
        detail: {
          message: "sync-policy.yaml schedules a system with no connection registered",
        },
      });
      continue;
    }
    await triggerSystem(pool, cfg, registered, {
      kind: "schedule",
      detail: { interval_s: sp.scheduleIntervalS, age_s: ageS },
    });
    triggered.push(system);
    log(`scheduler: ${system} due (age ${ageS ?? "∞"}s > ${sp.scheduleIntervalS}s) — snapshot triggered`);
  }

  await applyFreshness(pool, await computeFreshness(pool, policy));
  return { triggered, policy };
}

/** Periodic tick; returns a stop function. Policy-read failures surface
 * as health warnings and the tick is skipped (the KB host being down
 * must not crash the core). */
export function startScheduler(
  pool: pg.Pool,
  cfg: CoreConfig,
  log: (msg: string, err?: unknown) => void,
): () => void {
  const run = () => {
    schedulerTick(pool, cfg, log).catch(async (err) => {
      log("scheduler tick failed", err);
      await recordHealthEvent(pool, {
        kind: "sync_policy_unreadable",
        severity: "warning",
        detail: { message: (err as Error).message },
      }).catch(() => {});
    });
  };
  const timer = setInterval(run, cfg.sync.tickS * 1000);
  timer.unref();
  run(); // evaluate once at startup — a dead schedule warns immediately
  return () => clearInterval(timer);
}
