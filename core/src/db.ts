/**
 * Postgres access: the shared pool, a transaction helper, and the
 * LISTEN/NOTIFY wake channel that gives claims their sub-second latency
 * (J-3). One dedicated listener connection fans notifications out to an
 * in-process EventEmitter; claim waiters race that emitter against a
 * poll interval (maturing `not_before` jobs never NOTIFY).
 */

import { EventEmitter } from "node:events";
import pg from "pg";

export const JOBS_CHANNEL = "cl_jobs";

export function createPool(databaseUrl: string): pg.Pool {
  return new pg.Pool({ connectionString: databaseUrl, max: 20 });
}

export async function withTransaction<T>(
  pool: pg.Pool,
  fn: (client: pg.PoolClient) => Promise<T>,
): Promise<T> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // the original error is the one that matters
    }
    throw err;
  } finally {
    client.release();
  }
}

export class JobsNotifier {
  readonly events = new EventEmitter();
  private client: pg.Client | null = null;
  private stopped = false;

  constructor(private readonly databaseUrl: string) {
    this.events.setMaxListeners(0);
  }

  async start(): Promise<void> {
    const client = new pg.Client({ connectionString: this.databaseUrl });
    await client.connect();
    client.on("notification", () => this.events.emit("wake"));
    client.on("error", () => {
      // Connection dropped: claims degrade to their poll interval.
      if (!this.stopped) this.events.emit("wake");
    });
    await client.query(`LISTEN ${JOBS_CHANNEL}`);
    this.client = client;
  }

  /** Resolves on the next notification or after `timeoutMs`. */
  wait(timeoutMs: number): Promise<void> {
    return new Promise((resolve) => {
      const onWake = () => {
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(() => {
        this.events.removeListener("wake", onWake);
        resolve();
      }, timeoutMs);
      this.events.once("wake", onWake);
    });
  }

  async stop(): Promise<void> {
    this.stopped = true;
    if (this.client) {
      await this.client.end().catch(() => {});
      this.client = null;
    }
  }
}

export async function notifyJobs(
  queryable: pg.Pool | pg.PoolClient,
): Promise<void> {
  await queryable.query(`NOTIFY ${JOBS_CHANNEL}`);
}
