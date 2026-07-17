/**
 * Core configuration — environment-only (12-factor; Compose/Helm inject
 * the same variables). Every tunable the job protocol names has its §5
 * default here; tests shrink the time-based ones.
 */

import { readdirSync } from "node:fs";

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
  /** Sync orchestrator (CP-3b). Disabled unless SYNC_ENABLED; the job
   * API runs identically either way. */
  sync: SyncConfig;
}

export interface SyncConfig {
  enabled: boolean;
  /** KB repo remote: an https URL (github provider) or a local path to a
   * bare repo (local provider — tests, drills). */
  gitRemote: string;
  /** Fine-grained PAT for the contextlayer-sync machine account (D2).
   * Passed per git command via http.extraheader, never written to disk. */
  gitToken: string;
  gitProvider: "github" | "local";
  gitApiBase: string;
  baseBranch: string;
  committerName: string;
  committerEmail: string;
  /** argv prefix for the Python stage CLIs (ruling C2), like validatorCmd. */
  pythonCmd: string[];
  workdir: string;
  /** Scheduler tick cadence (§4.1, default hourly). */
  tickS: number;
  /** §5.2 acquisition budget default (SO-D; sync-policy.yaml overrides). */
  acquisitionBudgetS: number;
  acquirePollMs: number;
  /** §6 PR-stage bounded retries. */
  prRetries: number;
  prRetryBaseMs: number;
  /** §4.2 Content-Length cap for the webhook endpoint. */
  hookBodyMaxBytes: number;
  /** §10 wheel carry: the platform release's wheel, or null when this
   * deployment does not carry one. */
  wheelPath: string | null;
  wheelVersion: string | null;
  platformCommit: string | null;
  wheelBuilt: string | null;
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

/** SYNC_WHEEL_VERSION default: the version segment of a PEP-427 wheel
 * filename (`name-VERSION-…`). */
export function wheelVersionFromFilename(wheelPath: string): string | null {
  const base = wheelPath.split("/").pop() ?? "";
  const match = /^[A-Za-z0-9_.]+-([^-]+)-/.exec(base);
  return match ? match[1]! : null;
}

/** SYNC_WHEEL_PATH may name a directory holding exactly one .whl (how
 * the core image ships its build); resolve it to the wheel file. */
function resolveWheelPath(raw: string): string {
  try {
    const entries = readdirSync(raw).filter((f) => f.endsWith(".whl"));
    if (entries.length === 1) return `${raw.replace(/\/$/, "")}/${entries[0]!}`;
    if (entries.length > 1) {
      throw new ConfigError(`SYNC_WHEEL_PATH ${raw} holds ${entries.length} wheels`);
    }
  } catch (err) {
    if (err instanceof ConfigError) throw err;
    // not a directory — treat as a file path
  }
  return raw;
}

function loadSyncConfig(env: NodeJS.ProcessEnv): SyncConfig {
  const enabled = env.SYNC_ENABLED === "1" || env.SYNC_ENABLED === "true";
  const gitRemote = env.SYNC_GIT_REMOTE ?? "";
  if (enabled && !gitRemote) {
    throw new ConfigError("SYNC_GIT_REMOTE is required when SYNC_ENABLED");
  }
  const provider =
    env.SYNC_GIT_PROVIDER ?? (/^https?:\/\//.test(gitRemote) ? "github" : "local");
  if (provider !== "github" && provider !== "local") {
    throw new ConfigError(`SYNC_GIT_PROVIDER must be github or local, got ${provider}`);
  }
  const wheelPath = env.SYNC_WHEEL_PATH ? resolveWheelPath(env.SYNC_WHEEL_PATH) : null;
  return {
    enabled,
    gitRemote,
    gitToken: env.SYNC_GIT_TOKEN ?? "",
    gitProvider: provider,
    gitApiBase: (env.SYNC_GIT_API_BASE ?? "https://api.github.com").replace(/\/$/, ""),
    baseBranch: env.SYNC_GIT_BASE_BRANCH ?? "main",
    committerName: env.SYNC_COMMITTER_NAME ?? "contextlayer-sync",
    committerEmail: env.SYNC_COMMITTER_EMAIL ?? "sync@contextlayer.invalid",
    pythonCmd: (env.SYNC_PYTHON ?? "python3").split(/\s+/).filter(Boolean),
    workdir: env.SYNC_WORKDIR ?? "/tmp/cl-sync",
    tickS: intVar(env, "SYNC_TICK_S", 3600),
    acquisitionBudgetS: intVar(env, "SYNC_ACQUISITION_BUDGET_S", 2 * 3600),
    acquirePollMs: intVar(env, "SYNC_ACQUIRE_POLL_MS", 1000),
    prRetries: intVar(env, "SYNC_PR_RETRIES", 3),
    prRetryBaseMs: intVar(env, "SYNC_PR_RETRY_BASE_MS", 2000),
    hookBodyMaxBytes: intVar(env, "SYNC_HOOK_BODY_MAX", 64 * 1024),
    wheelPath,
    wheelVersion:
      env.SYNC_WHEEL_VERSION ?? (wheelPath ? wheelVersionFromFilename(wheelPath) : null),
    platformCommit: env.SYNC_PLATFORM_COMMIT ?? null,
    wheelBuilt: env.SYNC_WHEEL_BUILT ?? null,
  };
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
    sync: loadSyncConfig(env),
  };
}
