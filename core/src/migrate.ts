/**
 * Migrations runner (E1: versioned Postgres migrations, release
 * discipline per platform-architecture §3). Plain numbered .sql files
 * applied in filename order inside one transaction each, recorded in
 * `schema_migrations` with a checksum — a changed already-applied file
 * is an error, never silently re-run. An advisory lock serializes
 * concurrent replicas racing to migrate on start.
 */

import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import pg from "pg";

const MIGRATE_LOCK_KEY = 0x636c_6d69; // arbitrary app-wide constant

export interface AppliedMigration {
  version: string;
  checksum: string;
}

export async function migrate(
  pool: pg.Pool,
  dir: string,
  log: (msg: string) => void = () => {},
): Promise<AppliedMigration[]> {
  const files = (await readdir(dir)).filter((f) => f.endsWith(".sql")).sort();
  const client = await pool.connect();
  const applied: AppliedMigration[] = [];
  try {
    await client.query("SELECT pg_advisory_lock($1)", [MIGRATE_LOCK_KEY]);
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version    text PRIMARY KEY,
        checksum   text NOT NULL,
        applied_at timestamptz NOT NULL DEFAULT now()
      )`);
    const { rows } = await client.query<{ version: string; checksum: string }>(
      "SELECT version, checksum FROM schema_migrations",
    );
    const seen = new Map(rows.map((r) => [r.version, r.checksum]));

    for (const file of files) {
      const sql = await readFile(path.join(dir, file), "utf-8");
      const checksum = createHash("sha256").update(sql).digest("hex");
      const existing = seen.get(file);
      if (existing !== undefined) {
        if (existing !== checksum) {
          throw new Error(
            `migration ${file} changed after being applied ` +
              `(recorded ${existing.slice(0, 12)}, on disk ${checksum.slice(0, 12)})`,
          );
        }
        continue;
      }
      await client.query("BEGIN");
      try {
        await client.query(sql);
        await client.query(
          "INSERT INTO schema_migrations (version, checksum) VALUES ($1, $2)",
          [file, checksum],
        );
        await client.query("COMMIT");
      } catch (err) {
        await client.query("ROLLBACK").catch(() => {});
        throw new Error(`migration ${file} failed: ${(err as Error).message}`);
      }
      log(`applied migration ${file}`);
      applied.push({ version: file, checksum });
    }
    return applied;
  } finally {
    await client.query("SELECT pg_advisory_unlock($1)", [MIGRATE_LOCK_KEY]).catch(() => {});
    client.release();
  }
}

/** Repo-relative default: core/migrations next to the built dist/. */
export function defaultMigrationsDir(): string {
  return path.resolve(new URL(".", import.meta.url).pathname, "..", "migrations");
}
