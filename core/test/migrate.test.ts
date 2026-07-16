/**
 * Migrations runner discipline: idempotent re-runs, checksum guard on
 * applied files, all four ops tables land.
 */

import { cp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { mkdtemp } from "node:fs/promises";
import pg from "pg";
import { afterAll, beforeAll, expect, it } from "vitest";
import { createPool } from "../src/db.js";
import { migrate } from "../src/migrate.js";
import { createTestDb, repoRoot } from "./helpers.js";

const migrationsDir = path.resolve(repoRoot(), "core", "migrations");

let db: { url: string; drop: () => Promise<void> };
let pool: pg.Pool;

beforeAll(async () => {
  db = await createTestDb();
  pool = createPool(db.url);
});

afterAll(async () => {
  await pool.end();
  await db.drop();
});

it("applies all migrations once, then no-ops", async () => {
  const first = await migrate(pool, migrationsDir);
  expect(first.length).toBeGreaterThanOrEqual(4);
  const second = await migrate(pool, migrationsDir);
  expect(second).toHaveLength(0);

  const { rows } = await pool.query(
    `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'`,
  );
  const tables = rows.map((r) => r.table_name).sort();
  for (const expected of ["jobs", "accepted_snapshots", "runs", "health_events"]) {
    expect(tables).toContain(expected);
  }
});

it("refuses a changed already-applied migration", async () => {
  const copy = await mkdtemp(path.join(tmpdir(), "cl-migrations-"));
  await cp(migrationsDir, copy, { recursive: true });
  await writeFile(
    path.join(copy, "0001_jobs.sql"),
    "-- tampered\nSELECT 1;\n",
  );
  await expect(migrate(pool, copy)).rejects.toThrow(/changed after being applied/);
});
