/**
 * The audit contract (MCP spec §8, M-8, MCP-R13): one record per call,
 * including denied and filtered decisions with the true reason (M-4's
 * admin-debuggability half). `args_digest` is a hash over the canonical
 * JSON of the arguments; full statement/intent text is stored only for
 * validate/execute/publish. This table is the restricted deep store the
 * ledger's `audit_ref` points into (L-8).
 */

import { createHash } from "node:crypto";
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
