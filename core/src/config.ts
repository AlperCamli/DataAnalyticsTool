/**
 * Core configuration — environment-only (12-factor; Compose/Helm inject
 * the same variables). Every tunable the job protocol names has its §5
 * default here; tests shrink the time-based ones.
 */

export interface CoreConfig {
  databaseUrl: string;
  host: string;
  port: number;
  /** token → runner_id it is bound to, or null for an unbound token (J-8). */
  runnerTokens: Map<string, string | null>;
  /** argv for the Python delivery gate (C1): e.g. ["python3","-m","snapshot.accept"]. */
  validatorCmd: string[];
  migrateOnStart: boolean;
  logLevel: string;
  /** §5 defaults. */
  leaseTtlS: number;
  retryBaseS: number;
  retryCapS: number;
  maxDeferrals: number;
  /** JP-3: inline result cap (bytes) and per-system snapshot retention. */
  resultMaxBytes: number;
  snapshotRetention: number;
  /** Lease-expiry sweep cadence. */
  sweepIntervalMs: number;
  /** Claim long-poll re-check cadence (matured not_before jobs don't NOTIFY). */
  claimPollMs: number;
}

export class ConfigError extends Error {}

function intVar(env: NodeJS.ProcessEnv, name: string, fallback: number): number {
  const raw = env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new ConfigError(`${name} must be a positive number, got ${raw!}`);
  }
  return value;
}

/**
 * CORE_RUNNER_TOKENS: comma-separated entries, each either a bare token
 * (usable by any runner_id) or `runner-id=token` (bound). Per-runner
 * bound tokens are the intended deployment shape (J-8).
 */
export function parseRunnerTokens(raw: string): Map<string, string | null> {
  const tokens = new Map<string, string | null>();
  for (const entry of raw.split(",")) {
    const trimmed = entry.trim();
    if (!trimmed) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) {
      tokens.set(trimmed, null);
    } else {
      const runnerId = trimmed.slice(0, eq).trim();
      const token = trimmed.slice(eq + 1).trim();
      if (!runnerId || !token) {
        throw new ConfigError(`CORE_RUNNER_TOKENS entry ${JSON.stringify(entry)} is malformed`);
      }
      tokens.set(token, runnerId);
    }
  }
  if (tokens.size === 0) {
    throw new ConfigError("CORE_RUNNER_TOKENS defined no usable tokens");
  }
  return tokens;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): CoreConfig {
  const databaseUrl = env.CORE_DATABASE_URL;
  if (!databaseUrl) throw new ConfigError("CORE_DATABASE_URL is required");
  const rawTokens = env.CORE_RUNNER_TOKENS;
  if (!rawTokens) throw new ConfigError("CORE_RUNNER_TOKENS is required");

  const validatorCmd = (env.CORE_VALIDATOR_CMD ?? "python3 -m snapshot.accept")
    .split(/\s+/)
    .filter(Boolean);

  return {
    databaseUrl,
    host: env.CORE_HOST ?? "0.0.0.0",
    port: intVar(env, "CORE_PORT", 8100),
    runnerTokens: parseRunnerTokens(rawTokens),
    validatorCmd,
    migrateOnStart: env.CORE_MIGRATE_ON_START === "1" || env.CORE_MIGRATE_ON_START === "true",
    logLevel: env.CORE_LOG_LEVEL ?? "info",
    leaseTtlS: intVar(env, "CORE_LEASE_TTL_S", 60),
    retryBaseS: Number(env.CORE_RETRY_BASE_S ?? 30),
    retryCapS: intVar(env, "CORE_RETRY_CAP_S", 30 * 60),
    maxDeferrals: intVar(env, "CORE_MAX_DEFERRALS", 20),
    resultMaxBytes: intVar(env, "CORE_RESULT_MAX_BYTES", 64 * 1024 * 1024),
    snapshotRetention: intVar(env, "CORE_SNAPSHOT_RETENTION", 10),
    sweepIntervalMs: intVar(env, "CORE_SWEEP_INTERVAL_MS", 1000),
    claimPollMs: intVar(env, "CORE_CLAIM_POLL_MS", 300),
  };
}
