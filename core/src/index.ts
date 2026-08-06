/**
 * Core service entry point: config → (optional) migrations → job API +
 * lease sweeper. Structured logs via fastify/pino; SIGTERM/SIGINT drain
 * and exit.
 */

import { loadConfig } from "./config.js";
import { createPool, JobsNotifier, SYNC_CHANNEL } from "./db.js";
import { createProvider } from "./gitkb.js";
import { sweepResolutions, sweepRetention, sweepWindowRules } from "./ledger.js";
import { defaultMigrationsDir, migrate } from "./migrate.js";
import { failStaleRunningRuns, runPendingRuns } from "./pipeline.js";
import { startScheduler } from "./scheduler.js";
import { buildServer, startSweeper } from "./server.js";
import { resolveEnvReferences, VaultClient, vaultSettingsFromEnv } from "./vault.js";

async function main(): Promise<void> {
  // A-4: config values may be `vault://` references. Resolve them before
  // anything reads config, and fail the whole boot if any one of them
  // cannot be resolved — a core running on half its secrets fails later,
  // somewhere else, with a worse error. The names of the resolved
  // variables are logged; no value ever is (JC-8).
  const settings = vaultSettingsFromEnv(process.env);
  const vault = settings ? new VaultClient(settings) : null;
  const { env, resolved } = await resolveEnvReferences(process.env, vault);
  if (resolved.length > 0) {
    console.log(`vault: resolved ${resolved.length} config reference(s): ${resolved.join(", ")}`);
  }

  const cfg = loadConfig(env);
  const pool = createPool(cfg.databaseUrl);

  if (cfg.migrateOnStart) {
    await migrate(pool, defaultMigrationsDir(), (msg) => console.log(msg));
  }

  const notifier = new JobsNotifier(cfg.databaseUrl);
  await notifier.start();

  const app = buildServer(cfg, pool, notifier, undefined, { vault });
  const log = (msg: string, err?: unknown) =>
    err ? app.log.error({ err }, msg) : app.log.info(msg);
  const stopSweeper = startSweeper(pool, cfg, log);

  // Sync orchestrator (CP-3b): scheduler tick + NOTIFY-woken run loop.
  let stopScheduler = () => {};
  let syncNotifier: JobsNotifier | null = null;
  let syncLoopStopped = false;
  if (cfg.sync.enabled) {
    await failStaleRunningRuns(pool);
    stopScheduler = startScheduler(pool, cfg, log);
    syncNotifier = new JobsNotifier(cfg.databaseUrl, SYNC_CHANNEL);
    await syncNotifier.start();
    const deps = { pool, cfg, provider: createProvider(cfg.sync), log };
    void (async () => {
      while (!syncLoopStopped) {
        try {
          await runPendingRuns(deps);
        } catch (err) {
          log("sync run loop error", err);
        }
        await syncNotifier!.wait(60_000);
      }
    })();
  }

  // Ledger sweeps (CP-4): class-1 window rules, event retention (§10),
  // and CL-Resolves loop closure (§9, LED-R4) on one cadence.
  let stopLedgerSweeps = () => {};
  if (cfg.mcp.enabled) {
    const provider = cfg.sync.gitRemote ? createProvider(cfg.sync) : null;
    const timer = setInterval(() => {
      void (async () => {
        try {
          await sweepWindowRules(pool);
          await sweepRetention(pool, cfg.mcp.ledgerRetentionDays);
          if (provider) await sweepResolutions(pool, provider);
        } catch (err) {
          log("ledger sweep failed", err);
        }
      })();
    }, cfg.mcp.ledgerSweepMs);
    timer.unref();
    stopLedgerSweeps = () => clearInterval(timer);
  }

  const shutdown = async (signal: string) => {
    app.log.info({ signal }, "shutting down");
    stopSweeper();
    stopScheduler();
    stopLedgerSweeps();
    syncLoopStopped = true;
    await syncNotifier?.stop();
    await app.close();
    await notifier.stop();
    await pool.end();
    process.exit(0);
  };
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));

  await app.listen({ host: cfg.host, port: cfg.port });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
