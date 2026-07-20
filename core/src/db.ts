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
export const SYNC_CHANNEL = "cl_sync";
/**
 * Terminal-transition wake channel (CP-6). The claim side has had
 * LISTEN/NOTIFY since CP-3a; this is its mirror for the *producer*
 * side, so the execution gateway blocked on an interactive job learns
 * of `complete`/`fail` in sub-second time instead of polling.
 *
 * It has to be LISTEN/NOTIFY rather than an in-process EventEmitter:
 * the runner delivers its result to whichever core replica it claimed
 * against, which is not necessarily the replica holding the waiting
 * MCP request. An emitter would work on one node and silently stall on
 * two.
 */
export const JOB_DONE_CHANNEL = "cl_job_done";

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
  private readonly channel: string;

  constructor(private readonly databaseUrl: string, channel: string = JOBS_CHANNEL) {
    this.channel = channel;
    this.events.setMaxListeners(0);
  }

  async start(): Promise<void> {
    const client = new pg.Client({ connectionString: this.databaseUrl });
    await client.connect();
    client.on("notification", (msg) => this.events.emit("wake", msg.payload));
    client.on("error", () => {
      // Connection dropped: claims degrade to their poll interval.
      if (!this.stopped) this.events.emit("wake");
    });
    await client.query(`LISTEN ${this.channel}`);
    this.client = client;
  }

  /** Resolves on the next notification or after `timeoutMs`. */
  wait(timeoutMs: number): Promise<void> {
    return this.waitFor(() => true, timeoutMs);
  }

  /**
   * Resolves on the next notification whose payload satisfies `match`,
   * or after `timeoutMs`. Used by the execution gateway to wake on
   * *its* job finishing rather than on any queue activity.
   */
  waitFor(match: (payload: string | undefined) => boolean, timeoutMs: number): Promise<void> {
    return new Promise((resolve) => {
      const onWake = (payload?: string) => {
        if (!match(payload)) return; // someone else's job; keep waiting
        cleanup();
        resolve();
      };
      const cleanup = () => {
        clearTimeout(timer);
        this.events.removeListener("wake", onWake);
      };
      const timer = setTimeout(() => {
        this.events.removeListener("wake", onWake);
        resolve();
      }, timeoutMs);
      this.events.on("wake", onWake);
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

export async function notifySync(
  queryable: pg.Pool | pg.PoolClient,
): Promise<void> {
  await queryable.query(`NOTIFY ${SYNC_CHANNEL}`);
}

/** Wakes producers blocked on a specific interactive job (§6.4/§6.5). */
export async function notifyJobDone(
  queryable: pg.Pool | pg.PoolClient,
  jobId: string,
): Promise<void> {
  await queryable.query(`SELECT pg_notify($1, $2)`, [JOB_DONE_CHANNEL, jobId]);
}
