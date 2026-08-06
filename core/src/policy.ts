/**
 * sync-policy.yaml (sync spec §4.1, §8; location fixed by KB §3).
 *
 * Read from KB HEAD once per scheduler tick and once per run pin — no
 * cache beyond that (ruling E2; mirrors ledger L-3 config-not-code).
 * Unknown keys are tolerated (the file is customer-edited config, not a
 * closed contract like front-matter); missing values fall back to the
 * spec defaults (30 d freshness, §SO-D 2 h acquisition budget).
 */

import { parse as parseYaml } from "yaml";

export interface SystemPolicy {
  system: string;
  /** §8 threshold, seconds. Shipped default 30 d. */
  freshnessThresholdS: number;
  /** §4.1 scheduled interval, seconds; null = not scheduled. */
  scheduleIntervalS: number | null;
  /** Trigger modes as configured (for freshness guidance wording, SY-7). */
  webhook: boolean;
  manual: boolean;
}

export interface SyncPolicy {
  systems: Map<string, SystemPolicy>;
  /** SO-D: run acquisition budget override, seconds. */
  acquisitionBudgetS: number | null;
}

export class PolicyError extends Error {}

const DEFAULT_FRESHNESS_S = 30 * 24 * 3600;

const DURATION = /^(\d+)\s*(s|m|h|d|w)$/;
const UNIT_S: Record<string, number> = { s: 1, m: 60, h: 3600, d: 86400, w: 604800 };

/** "3d" / "12h" / "45m" / plain seconds → seconds. */
export function durationS(value: unknown, context: string): number {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === "string") {
    const match = DURATION.exec(value.trim());
    if (match) return Number(match[1]) * UNIT_S[match[2]!]!;
  }
  throw new PolicyError(`${context}: cannot parse duration ${JSON.stringify(value)}`);
}

export function parsePolicy(text: string): SyncPolicy {
  let doc: unknown;
  try {
    doc = parseYaml(text);
  } catch (err) {
    throw new PolicyError(`sync-policy.yaml does not parse: ${(err as Error).message}`);
  }
  return policyFromDoc(doc);
}

/**
 * The parse, from an already-loaded document.
 *
 * The KB workspace (`KbState.syncPolicy`) has read and parsed this file
 * once already; the dashboard's KB Health read uses *that* rather than
 * fetching the file a second time, so the two surfaces cannot disagree
 * about a threshold while both claim to be reading HEAD. Same rule as
 * fan-out, applied to a file instead of a value.
 */
export function policyFromDoc(doc: unknown): SyncPolicy {
  const systemsRaw = (doc as { systems?: unknown })?.systems;
  // An array is an object in JS, and `Object.entries` over one yields
  // "0", "1", "2" as system names — a policy that parses cleanly and
  // matches no real system, so nothing syncs and nothing complains.
  // That is the silent-failure family this project keeps meeting, so a
  // list here is an error rather than a policy about systems 0 and 1.
  if (typeof systemsRaw !== "object" || systemsRaw === null || Array.isArray(systemsRaw)) {
    throw new PolicyError("sync-policy.yaml has no systems map (a list is not a map of system names)");
  }
  const systems = new Map<string, SystemPolicy>();
  for (const [system, raw] of Object.entries(systemsRaw as Record<string, unknown>)) {
    const entry = (raw ?? {}) as Record<string, unknown>;
    const triggers = (entry.triggers ?? {}) as Record<string, unknown>;
    const schedule = triggers.schedule;
    systems.set(system, {
      system,
      freshnessThresholdS:
        entry.freshness_threshold === undefined || entry.freshness_threshold === null
          ? DEFAULT_FRESHNESS_S
          : durationS(entry.freshness_threshold, `${system}.freshness_threshold`),
      scheduleIntervalS:
        schedule === undefined || schedule === null || schedule === false
          ? null
          : durationS(schedule, `${system}.triggers.schedule`),
      webhook: Boolean(triggers.webhook),
      manual: triggers.manual !== false,
    });
  }
  const budget = (doc as { acquisition_budget?: unknown }).acquisition_budget;
  return {
    systems,
    acquisitionBudgetS:
      budget === undefined || budget === null
        ? null
        : durationS(budget, "acquisition_budget"),
  };
}
