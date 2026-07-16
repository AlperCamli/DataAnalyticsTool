/**
 * Core service entry point: config → (optional) migrations → job API +
 * lease sweeper. Structured logs via fastify/pino; SIGTERM/SIGINT drain
 * and exit.
 */

import { loadConfig } from "./config.js";
import { createPool, JobsNotifier } from "./db.js";
import { defaultMigrationsDir, migrate } from "./migrate.js";
import { buildServer, startSweeper } from "./server.js";

async function main(): Promise<void> {
  const cfg = loadConfig();
  const pool = createPool(cfg.databaseUrl);

  if (cfg.migrateOnStart) {
    await migrate(pool, defaultMigrationsDir(), (msg) => console.log(msg));
  }

  const notifier = new JobsNotifier(cfg.databaseUrl);
  await notifier.start();

  const app = buildServer(cfg, pool, notifier);
  const stopSweeper = startSweeper(pool, cfg, (msg, err) =>
    err ? app.log.error({ err }, msg) : app.log.info(msg),
  );

  const shutdown = async (signal: string) => {
    app.log.info({ signal }, "shutting down");
    stopSweeper();
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
