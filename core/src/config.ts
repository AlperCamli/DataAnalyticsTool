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
  /** P-A auth split (D-66.1): service-identity tokens for the
   * producer/ops/read surface — a set distinct from runnerTokens.
   * token → service name (or null for an unnamed token). */
  opsTokens: Map<string, string | null>;
  /** OIDC roles that also unlock the ops surface (platform identity). */
  opsRoles: string[];
  /** MCP server (CP-4). Disabled unless CORE_MCP_ENABLED. */
  mcp: McpConfig;
  /** Dashboard read APIs + browser sessions (B-0). */
  dashboard: DashboardConfig;
}

/**
 * Dashboard surface (dashboard spec §5, D-102.1). It shares the core's
 * identity domain and KB by ruling (UI-9: one release train, one config
 * source, one identity domain), so it is enabled with the MCP surface
 * unless CORE_DASHBOARD_ENABLED says otherwise — there is no second
 * deployment to turn on.
 */
export interface DashboardConfig {
  enabled: boolean;
  /** Post-login landing path (the SPA's entry point once B-1 ships). */
  postLoginPath: string;
  /** Session lifetime cap; the IdP's token lifetime still wins when
   * shorter (D-102.1: expiry follows the IdP's token lifetimes). */
  sessionMaxS: number;
  /** `Secure` on the session cookie. Defaults to on for an https
   * public URL, off for plain-http local/dev so the pilot works. */
  cookieSecure: boolean;
  /** UI-B: page size default and hard cap for every read endpoint. */
  pageDefault: number;
  pageMax: number;
  /** Approved requests stamped by one "deliver batch" trigger
   * (ledger §8: batches are cut on demand or at ~10). */
  batchMax: number;
}

export interface McpConfig {
  enabled: boolean;
  /** Public base URL for OAuth protected-resource metadata (RFC 9728). */
  publicUrl: string;
  /** Customer IdP issuer; identity is resolved per call via token
   * introspection so revocation is immediate (MCP-R1, MT-9). */
  oidcIssuer: string;
  oidcClientId: string;
  oidcClientSecret: string;
  /** Claim path holding the caller's roles (dotted; e.g.
   * `realm_access.roles` for Keycloak-shaped IdPs). */
  rolesClaim: string;
  /** KB HEAD re-check TTL for the per-call read (0 = every call). */
  kbRefreshMs: number;
  /** Validation-token TTL (MC-2 default 300 s). */
  vtokenTtlS: number;
  /** §7 per-identity rate limits. */
  limits: {
    readPerMin: number;
    validatePerMin: number;
    executePerMin: number;
    publishPerHour: number;
    flagPerSession: number;
  };
  /** Ledger §10 event retention and the sweep cadence for window rules,
   * retention, and CL-Resolves resolution polling. */
  ledgerRetentionDays: number;
  ledgerSweepMs: number;
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

function loadMcpConfig(env: NodeJS.ProcessEnv, host: string, port: number): McpConfig {
  const enabled = env.CORE_MCP_ENABLED === "1" || env.CORE_MCP_ENABLED === "true";
  const oidcIssuer = (env.CORE_OIDC_ISSUER ?? "").replace(/\/$/, "");
  if (enabled && !oidcIssuer) {
    throw new ConfigError("CORE_OIDC_ISSUER is required when CORE_MCP_ENABLED");
  }
  if (enabled && !env.SYNC_GIT_REMOTE) {
    throw new ConfigError("SYNC_GIT_REMOTE (the KB remote) is required when CORE_MCP_ENABLED");
  }
  return {
    enabled,
    publicUrl: (env.CORE_PUBLIC_URL ?? `http://${host}:${port}`).replace(/\/$/, ""),
    oidcIssuer,
    oidcClientId: env.CORE_OIDC_CLIENT_ID ?? "",
    oidcClientSecret: env.CORE_OIDC_CLIENT_SECRET ?? "",
    rolesClaim: env.CORE_OIDC_ROLES_CLAIM ?? "roles",
    kbRefreshMs: Number(env.CORE_KB_REFRESH_MS ?? 5000),
    vtokenTtlS: intVar(env, "CORE_VTOKEN_TTL_S", 300),
    limits: {
      readPerMin: intVar(env, "CORE_MCP_READ_PER_MIN", 120),
      validatePerMin: intVar(env, "CORE_MCP_VALIDATE_PER_MIN", 20),
      executePerMin: intVar(env, "CORE_MCP_EXECUTE_PER_MIN", 6),
      publishPerHour: intVar(env, "CORE_MCP_PUBLISH_PER_HOUR", 4),
      flagPerSession: intVar(env, "CORE_MCP_FLAG_PER_SESSION", 10),
    },
    ledgerRetentionDays: intVar(env, "CORE_LEDGER_RETENTION_DAYS", 90),
    ledgerSweepMs: intVar(env, "CORE_LEDGER_SWEEP_MS", 5 * 60 * 1000),
  };
}

function loadDashboardConfig(
  env: NodeJS.ProcessEnv,
  mcp: McpConfig,
): DashboardConfig {
  const raw = env.CORE_DASHBOARD_ENABLED;
  const enabled = raw === undefined || raw === "" ? mcp.enabled : raw === "1" || raw === "true";
  if (enabled && !mcp.oidcIssuer) {
    throw new ConfigError("CORE_OIDC_ISSUER is required when the dashboard is enabled");
  }
  const pageDefault = intVar(env, "CORE_DASHBOARD_PAGE_DEFAULT", 50);
  const pageMax = intVar(env, "CORE_DASHBOARD_PAGE_MAX", 200);
  if (pageDefault > pageMax) {
    throw new ConfigError(
      `CORE_DASHBOARD_PAGE_DEFAULT (${pageDefault}) exceeds CORE_DASHBOARD_PAGE_MAX (${pageMax})`,
    );
  }
  return {
    enabled,
    postLoginPath: env.CORE_DASHBOARD_POST_LOGIN ?? "/",
    sessionMaxS: intVar(env, "CORE_DASHBOARD_SESSION_MAX_S", 12 * 3600),
    cookieSecure:
      env.CORE_DASHBOARD_COOKIE_SECURE !== undefined && env.CORE_DASHBOARD_COOKIE_SECURE !== ""
        ? env.CORE_DASHBOARD_COOKIE_SECURE === "1" || env.CORE_DASHBOARD_COOKIE_SECURE === "true"
        : mcp.publicUrl.startsWith("https://"),
    pageDefault,
    pageMax,
    batchMax: intVar(env, "CORE_DASHBOARD_BATCH_MAX", 10),
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

  const host = env.CORE_HOST ?? "0.0.0.0";
  const port = intVar(env, "CORE_PORT", 8100);
  const mcp = loadMcpConfig(env, host, port);
  return {
    databaseUrl,
    host,
    port,
    runnerTokens: parseRunnerTokens(rawTokens),
    opsTokens: env.CORE_OPS_TOKENS ? parseRunnerTokens(env.CORE_OPS_TOKENS) : new Map(),
    opsRoles: (env.CORE_OPS_ROLES ?? "ops,steward").split(",").map((r) => r.trim()).filter(Boolean),
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
    mcp,
    dashboard: loadDashboardConfig(env, mcp),
  };
}
