/**
 * The audit contract (MCP spec §8, M-8, MCP-R13): one record per call,
 * including denied and filtered decisions with the true reason (M-4's
 * admin-debuggability half). `args_digest` is a hash over the canonical
 * JSON of the arguments; full statement/intent text is stored only for
 * validate/execute/publish. This table is the restricted deep store the
 * ledger's `audit_ref` points into (L-8).
 */

import { createHash, randomUUID } from "node:crypto";
import pg from "pg";

export interface AuditRecord {
  auditId: string;
  subject: string;
  roles: string[];
  profile: string | null;
  sessionId: string | null;
  tool: string;
  args: unknown;
  kbRef: string | null;
  snapshotRef: Record<string, string> | null;
  decision: "allowed" | "denied" | "filtered";
  decisionReason: string | null;
  durationMs: number;
  resultMeta: Record<string, unknown>;
  statementText: string | null;
  /**
   * D-108.4 / PA-3: the compiled-setup stamp the session presented on
   * its MCP URL, or the literal `unstamped` when it presented none.
   * Not optional — a caller that forgets it would write NULL, which
   * this column reserves for rows that predate it (see migration
   * 0011). The value is the client's claim about itself, and pairs
   * with the server's own comparison: PA-2's notice says whether it
   * matched, this column says what it was.
   */
  setupStamp: string;
}

/** The value written when a session presents no stamp at all. */
export const UNSTAMPED = "unstamped";

/** Deterministic JSON: object keys sorted at every level. */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([k, v]) => `${JSON.stringify(k)}:${canonicalJson(v)}`);
  return `{${entries.join(",")}}`;
}

export function argsDigest(args: unknown): string {
  return createHash("sha256").update(canonicalJson(args ?? {})).digest("hex");
}

/**
 * A governance write, recorded (D-114.1 — closes dashboard spec §5.1).
 *
 * §5.1 filed the gap plainly: `audit_records` is one row per MCP call
 * and is exactly that, so connection CRUD — and every governance write
 * after it — left no durable record beyond a job's `triggers` array,
 * which exists only where a job exists. A registration that enqueues
 * nothing left nothing behind.
 *
 * **The contract widens from "one row per MCP call" to "one row per
 * governed act."** No schema change was needed; the table was already
 * tool-agnostic. Every existing consumer filters by `tool` (the ledger's
 * window rules name `validate_sql` and `execute_sql`/`publish_report`;
 * the deliveries read joins on `audit_id`), so none re-reads differently.
 *
 * Two shapes are deliberate. `session_id` and `setup_stamp` are null and
 * `unstamped`: a browser session is not an MCP session and presents no
 * compiled-setup stamp, and inventing values for those columns would
 * make governance rows look like tool calls in exactly the register
 * meant to tell them apart. And **`denied` is recorded**, not only
 * `allowed` — a reporter's refused verdict attempt is precisely the row
 * an auditor wants, and a success-only log would omit it.
 *
 * The write is best-effort *for the caller's outcome*: an audit failure
 * is logged and does not fail the act, because a governance write that
 * already succeeded must not be reported as failed. It is not silent —
 * the log line is the alarm.
 */
export async function writeGovernanceAudit(
  pool: pg.Pool,
  rec: {
    subject: string;
    roles: string[];
    profile: string | null;
    /** `dashboard.<module>.<act>` — the act, not an MCP tool name. */
    tool: string;
    args: unknown;
    kbRef: string | null;
    decision: "allowed" | "denied";
    decisionReason: string | null;
    resultMeta?: Record<string, unknown>;
  },
  log?: (msg: string, err?: unknown) => void,
): Promise<void> {
  try {
    await writeAudit(pool, {
      auditId: randomUUID(),
      subject: rec.subject,
      roles: rec.roles,
      profile: rec.profile,
      sessionId: null,
      tool: rec.tool,
      args: rec.args,
      kbRef: rec.kbRef,
      snapshotRef: null,
      decision: rec.decision,
      decisionReason: rec.decisionReason,
      durationMs: 0,
      resultMeta: rec.resultMeta ?? {},
      statementText: null,
      setupStamp: UNSTAMPED,
    });
  } catch (err) {
    log?.("governance audit write failed", err);
  }
}

export async function writeAudit(pool: pg.Pool, rec: AuditRecord): Promise<void> {
  await pool.query(
    `INSERT INTO audit_records
       (audit_id, subject, roles, profile, session_id, tool, args_digest,
        kb_ref, snapshot_ref, decision, decision_reason, duration_ms,
        result_meta, statement_text, setup_stamp)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`,
    [
      rec.auditId,
      rec.subject,
      rec.roles,
      rec.profile,
      rec.sessionId,
      rec.tool,
      argsDigest(rec.args),
      rec.kbRef,
      rec.snapshotRef === null ? null : JSON.stringify(rec.snapshotRef),
      rec.decision,
      rec.decisionReason,
      rec.durationMs,
      JSON.stringify(rec.resultMeta),
      rec.statementText,
      rec.setupStamp,
    ],
  );
}
