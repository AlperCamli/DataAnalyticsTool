/**
 * Fault ledger (fault-ledger spec): append-only events deduplicated
 * into lifecycle-bearing issues (L-1) by fingerprint (§3.3), class-1
 * detector rules as ops configuration (L-3), flag_gap/list_gaps
 * ingestion and reads, CL-Resolves loop closure (L-5, LED-R4),
 * recurrence reopen (L-4), and the retention sweep (§10).
 *
 * LED-R2 (D-66.5 amendment) is enforced at *storage*: query-term
 * scopes, generated titles, and descriptions are scrubbed of
 * value-shaped tokens and length-bounded before they ever land in a
 * row; LED-R5 neutralizes them again at every render point.
 */

import { createHash, randomUUID } from "node:crypto";
import pg from "pg";
import type { MergedPr, PrProvider } from "./gitkb.js";

export const FLAG_GAP_KINDS = [
  "missing_doc",
  "missing_join_path",
  "uncertified_metric",
  "missing_entity",
  "schema_mismatch",
  "capability_gap",
  "result_disputed",
  // MCP §6.10 amendment (D-101.3): reachable from a session, because a
  // queue only browser users can file into is not the queue D-101 adopted.
  "enrichment_request",
  "other",
] as const;

/** flag_gap's enum maps onto the §4 registry; `schema_mismatch` lands on
 * the doc_schema_mismatch fingerprint so both classes corroborate one
 * issue (L-2). */
export function registryKind(flagKind: string): string {
  return flagKind === "schema_mismatch" ? "doc_schema_mismatch" : flagKind;
}

const STOPWORDS = new Set([
  "a", "an", "the", "of", "by", "for", "in", "on", "to", "and", "or", "with",
  "per", "vs", "at", "from", "into", "is", "are", "was", "be", "how", "what",
  "which", "who", "show", "me", "my", "our", "their", "get", "list", "all",
]);

const EMAIL_RE = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;
const QUOTED_RE = /"[^"]*"|'[^']*'/g;
const DIGIT_RUN_RE = /\b\w*\d{4,}\w*\b/g;
const NUMBER_RE = /\b\d+(?:[.,]\d+)*\b/g;

export const TITLE_MAX = 160;
export const DESCRIPTION_MAX = 500;
/**
 * D-106.4 decoupled this from `DESCRIPTION_MAX` **by intent**: suggested
 * content legitimately carries enum decodings and structure sketches,
 * which a gap description never does. The defense against data-value
 * dumping is the LED-R2 scrub above — not brevity — so the bound is
 * generous and the scrub is unchanged. A description stays 500.
 */
export const PROPOSAL_MAX = 2000;
/** Rejection reasons are shown to the filer, so LED-R2 binds them too. */
export const VERDICT_REASON_MAX = DESCRIPTION_MAX;

/** The kind that carries the verdict lifecycle (ledger §4 amendment). */
export const ENRICHMENT_REQUEST = "enrichment_request";

/** Inlet for the dashboard's human gap form (§4 registry, class 3). */
export const HUMAN_FILED = "human_filed";

/** LED-R2 storage scrub: value-shaped content never lands in the ledger. */
export function scrubText(text: string, max: number): string {
  return text
    .replace(QUOTED_RE, " ")
    .replace(EMAIL_RE, " ")
    .replace(UUID_RE, " ")
    .replace(DIGIT_RUN_RE, " ")
    .replace(NUMBER_RE, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
}

/** §3.3 normalized query terms, post-scrub: lowercased, stopwords
 * stripped, sorted — stable across users and phrasings. */
export function normalizeQueryTerms(text: string): string {
  const scrubbed = scrubText(text.toLowerCase(), 1000);
  const tokens = (scrubbed.match(/[a-z][a-z0-9_-]*/g) ?? []).filter((t) => !STOPWORDS.has(t));
  return [...new Set(tokens)].sort().join(" ");
}

export function fingerprintOf(kind: string, scope: string): string {
  return createHash("sha256").update(`${kind}‖${scope}`).digest("hex");
}

export interface LedgerEventInput {
  detectorClass: 1 | 2 | 3;
  kind: string;
  scope: string; // fingerprint scope (§3.3), already object FQN or normalized terms
  scopeLabel?: string; // human title fragment; defaults to scope
  system?: string | null;
  objectFqn?: string | null;
  subject?: string | null;
  sessionId?: string | null;
  profile?: string | null;
  auditRef?: string | null;
  kbRef?: string | null;
  snapshotRef?: Record<string, string> | null;
  description?: string | null;
  detail?: Record<string, unknown>;
  ts?: Date;
}

export interface LedgerEventResult {
  issueId: string;
  occurrences: number;
  routedTo: string;
}

async function routeFor(client: pg.PoolClient, kind: string): Promise<string> {
  const { rows } = await client.query<{ routed_to: string }>(
    `SELECT routed_to FROM ledger_routing WHERE kind = $1
      UNION ALL
     SELECT routed_to FROM ledger_routing WHERE kind = '__default__'
      LIMIT 1`,
    [kind],
  );
  return rows[0]?.routed_to ?? "data-team";
}

/** Ingest one event: upsert the issue (increment / create / L-4 reopen),
 * insert the event, refresh distinct_subjects. */
export async function recordEvent(pool: pg.Pool, input: LedgerEventInput): Promise<LedgerEventResult> {
  const fingerprint = fingerprintOf(input.kind, input.scope);
  const ts = input.ts ?? new Date();
  const title = scrubText(`${input.kind}: ${input.scopeLabel ?? input.scope}`, TITLE_MAX);
  const description = input.description ? scrubText(input.description, DESCRIPTION_MAX) : null;
  // LED-R2 for the §4 amendment's proposal payload, enforced *here* —
  // at storage, on the one path both inlets share (the dashboard's
  // request form and flag_gap) — so no inlet can carry an unscrubbed or
  // unbounded value into a row, whatever it passes.
  const detail = { ...(input.detail ?? {}) };
  if (typeof detail.proposal === "string") {
    detail.proposal = scrubText(detail.proposal, PROPOSAL_MAX);
  }
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const routedTo = await routeFor(client, input.kind);
    const { rows } = await client.query<{ issue_id: string; occurrences: number }>(
      `INSERT INTO ledger_issues
         (issue_id, fingerprint, kind, system, object_fqn, title, routed_to,
          first_seen, last_seen, occurrences, distinct_subjects)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, 1, 0)
       -- L-4 recurrence, with 'rejected' in the reopening set by D-106.5:
       -- a request refiled after a rejection is the same signal a
       -- reoccurring wont_fix is, so it reopens on the same rule. The
       -- verdict columns are deliberately NOT cleared — the steward
       -- reads "rejected before, refiled by N more" and may re-reject.
       ON CONFLICT (fingerprint) DO UPDATE SET
         occurrences = ledger_issues.occurrences + 1,
         last_seen   = EXCLUDED.last_seen,
         reopen_count = CASE WHEN ledger_issues.status IN ('resolved','dismissed','rejected')
                             THEN ledger_issues.reopen_count + 1
                             ELSE ledger_issues.reopen_count END,
         status      = CASE WHEN ledger_issues.status IN ('resolved','dismissed','rejected')
                            THEN 'open' ELSE ledger_issues.status END
       RETURNING issue_id, occurrences`,
      [
        randomUUID(),
        fingerprint,
        input.kind,
        input.system ?? null,
        input.objectFqn ?? null,
        title,
        routedTo,
        ts,
      ],
    );
    const issue = rows[0]!;
    await client.query(
      `INSERT INTO ledger_events
         (event_id, ts, detector_class, kind, fingerprint, system, object_fqn,
          subject, session_id, profile, audit_ref, kb_ref, snapshot_ref,
          description, detail, issue_id)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)`,
      [
        randomUUID(),
        ts,
        input.detectorClass,
        input.kind,
        fingerprint,
        input.system ?? null,
        input.objectFqn ?? null,
        input.subject ?? null,
        input.sessionId ?? null,
        input.profile ?? null,
        input.auditRef ?? null,
        input.kbRef ?? null,
        input.snapshotRef ? JSON.stringify(input.snapshotRef) : null,
        description,
        JSON.stringify(detail),
        issue.issue_id,
      ],
    );
    await client.query(
      `UPDATE ledger_issues SET distinct_subjects =
         (SELECT count(DISTINCT subject) FROM ledger_events
           WHERE issue_id = $1 AND subject IS NOT NULL)
       WHERE issue_id = $1`,
      [issue.issue_id],
    );
    await client.query("COMMIT");
    return {
      issueId: issue.issue_id,
      occurrences: issue.occurrences,
      routedTo,
    };
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

export interface GapIssue {
  issue_id: string;
  kind: string;
  title: string;
  object_fqn: string | null;
  system: string | null;
  status: string;
  occurrences: number;
  distinct_subjects: number;
  first_seen: string;
  last_seen: string;
  links: Record<string, unknown>;
}

/** list_gaps reads (§8): counts only (LED-R7); the caller applies the
 * visibility filter (LED-R2) and render neutralization (LED-R5). */
export async function listIssues(
  pool: pg.Pool,
  filter: { status?: string; kind?: string; system?: string; limit?: number },
): Promise<GapIssue[]> {
  const params: unknown[] = [];
  const where: string[] = [];
  const status = filter.status ?? "open";
  params.push(status);
  where.push(`status = $${params.length}`);
  if (filter.kind) {
    params.push(filter.kind);
    where.push(`kind = $${params.length}`);
  }
  if (filter.system) {
    params.push(filter.system);
    where.push(`system = $${params.length}`);
  }
  params.push(Math.min(filter.limit ?? 20, 100));
  const { rows } = await pool.query<GapIssue>(
    `SELECT issue_id, kind, title, object_fqn, system, status, occurrences,
            distinct_subjects, first_seen, last_seen, links
       FROM ledger_issues
      WHERE ${where.join(" AND ")}
      ORDER BY occurrences DESC, last_seen DESC, issue_id
      LIMIT $${params.length}`,
    params,
  );
  return rows;
}

// ---------------------------------------------------------------------------
// Triage-queue contract (§8) and the enrichment_request verdict
// lifecycle (§4 amendment, D-101.2) — the dashboard's ledger surface.
//
// Kept beside `listIssues` rather than in the dashboard module so the
// ledger's own rules (ordering, scrub bounds, state machine) stay in the
// ledger, and the dashboard remains a caller of them.

export interface TriageIssue extends GapIssue {
  detector_class: number | null;
  /** L-4 recurrences, including the post-rejection refilings D-106.5
   * added: the "refiled by N more" half of what a steward re-reads. */
  reopen_count: number;
  verdict_by: string | null;
  verdict_at: string | null;
  verdict_reason: string | null;
  batch_id: string | null;
  resolution: Record<string, unknown> | null;
  /** The enrich skill's note when it handed this request back rather
   * than guessing at it (§4: `batched → approved`, note recorded). */
  return_note: string | null;
  returned_at: string | null;
}

export interface TriageFilter {
  /** Empty = every status (the queue's default is the open-ish set). */
  statuses?: string[];
  kind?: string;
  system?: string;
  /**
   * Restrict to issues this subject has filed an event on. This is the
   * server-side subject filter behind DT-1 for the ledger endpoint: a
   * reporter's queue is the requests they filed, never anyone else's.
   */
  filedBy?: string;
  limit: number;
  /** Keyset cursor: continue strictly after this issue in queue order. */
  after?: { occurrences: number; distinctSubjects: number; lastSeen: string; issueId: string };
}

/**
 * §8 queue order: the prioritization signal the queue already has —
 * `(occurrences, distinct_subjects)`, then recency, then a stable id
 * tiebreak so keyset pagination cannot skip or repeat a row.
 */
export async function listTriageIssues(pool: pg.Pool, filter: TriageFilter): Promise<TriageIssue[]> {
  const params: unknown[] = [];
  const where: string[] = [];
  if (filter.statuses && filter.statuses.length > 0) {
    params.push(filter.statuses);
    where.push(`i.status = ANY($${params.length})`);
  }
  if (filter.kind) {
    params.push(filter.kind);
    where.push(`i.kind = $${params.length}`);
  }
  if (filter.system) {
    params.push(filter.system);
    where.push(`i.system = $${params.length}`);
  }
  if (filter.filedBy !== undefined) {
    params.push(filter.filedBy);
    where.push(
      `EXISTS (SELECT 1 FROM ledger_events e
                WHERE e.issue_id = i.issue_id AND e.subject = $${params.length})`,
    );
  }
  if (filter.after) {
    params.push(filter.after.occurrences, filter.after.distinctSubjects, filter.after.lastSeen, filter.after.issueId);
    const n = params.length;
    where.push(
      `(i.occurrences, i.distinct_subjects, i.last_seen, i.issue_id) <
       ($${n - 3}::integer, $${n - 2}::integer, $${n - 1}::timestamptz, $${n}::uuid)`,
    );
  }
  params.push(filter.limit);
  const { rows } = await pool.query<TriageIssue>(
    `SELECT i.issue_id, i.kind, i.title, i.object_fqn, i.system, i.status,
            i.occurrences, i.distinct_subjects,
            to_jsonb(i.first_seen) #>> '{}' AS first_seen,
            to_jsonb(i.last_seen)  #>> '{}' AS last_seen,
            i.links, i.reopen_count, i.verdict_by,
            to_jsonb(i.verdict_at) #>> '{}' AS verdict_at,
            i.verdict_reason, i.batch_id, i.resolution, i.return_note,
            to_jsonb(i.returned_at) #>> '{}' AS returned_at,
            (SELECT max(e.detector_class) FROM ledger_events e
              WHERE e.issue_id = i.issue_id) AS detector_class
       FROM ledger_issues i
      ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
      ORDER BY i.occurrences DESC, i.distinct_subjects DESC, i.last_seen DESC, i.issue_id DESC
      LIMIT $${params.length}`,
    params,
  );
  return rows;
}

export interface LedgerEventRow {
  event_id: string;
  ts: string;
  detector_class: number;
  kind: string;
  system: string | null;
  object_fqn: string | null;
  subject: string | null;
  session_id: string | null;
  profile: string | null;
  audit_ref: string | null;
  kb_ref: string | null;
  description: string | null;
  detail: Record<string, unknown>;
  issue_id: string;
  /** Issue-level context, so an event stream can be rendered alone. */
  issue_status: string;
  issue_kind: string;
  routed_to: string;
}

/** §8 issue view: the event stream behind one issue, or a whole window
 * of events when no issue is named (the evidence-extraction read). */
export async function listEvents(
  pool: pg.Pool,
  filter: { issueId?: string; since?: string; until?: string; kind?: string; subject?: string; limit: number; after?: { ts: string; eventId: string } },
): Promise<LedgerEventRow[]> {
  const params: unknown[] = [];
  const where: string[] = [];
  if (filter.issueId) {
    params.push(filter.issueId);
    where.push(`e.issue_id = $${params.length}::uuid`);
  }
  if (filter.since) {
    params.push(filter.since);
    where.push(`e.ts >= $${params.length}::timestamptz`);
  }
  if (filter.until) {
    params.push(filter.until);
    where.push(`e.ts <= $${params.length}::timestamptz`);
  }
  if (filter.kind) {
    params.push(filter.kind);
    where.push(`e.kind = $${params.length}`);
  }
  if (filter.subject !== undefined) {
    params.push(filter.subject);
    where.push(`e.subject = $${params.length}`);
  }
  if (filter.after) {
    params.push(filter.after.ts, filter.after.eventId);
    const n = params.length;
    where.push(`(e.ts, e.event_id) > ($${n - 1}::timestamptz, $${n}::uuid)`);
  }
  params.push(filter.limit);
  const { rows } = await pool.query<LedgerEventRow>(
    `SELECT e.event_id, to_jsonb(e.ts) #>> '{}' AS ts,
            e.detector_class, e.kind, e.system, e.object_fqn,
            e.subject, e.session_id, e.profile, e.audit_ref, e.kb_ref,
            e.description, e.detail, e.issue_id,
            i.status AS issue_status, i.kind AS issue_kind, i.routed_to
       FROM ledger_events e
       JOIN ledger_issues i ON i.issue_id = e.issue_id
      ${where.length ? `WHERE ${where.join(" AND ")}` : ""}
      ORDER BY e.ts, e.event_id
      LIMIT $${params.length}`,
    params,
  );
  return rows;
}

export async function getIssue(pool: pg.Pool, issueId: string): Promise<TriageIssue | null> {
  const { rows } = await pool.query<TriageIssue>(
    `SELECT i.issue_id, i.kind, i.title, i.object_fqn, i.system, i.status,
            i.occurrences, i.distinct_subjects,
            to_jsonb(i.first_seen) #>> '{}' AS first_seen,
            to_jsonb(i.last_seen)  #>> '{}' AS last_seen,
            i.links, i.reopen_count, i.verdict_by,
            to_jsonb(i.verdict_at) #>> '{}' AS verdict_at,
            i.verdict_reason, i.batch_id, i.resolution, i.return_note,
            to_jsonb(i.returned_at) #>> '{}' AS returned_at,
            (SELECT max(e.detector_class) FROM ledger_events e
              WHERE e.issue_id = i.issue_id) AS detector_class
       FROM ledger_issues i WHERE i.issue_id = $1::uuid`,
    [issueId],
  );
  return rows[0] ?? null;
}

export type VerdictOutcome =
  | { ok: true; issue: TriageIssue }
  | { ok: false; code: "not_found" | "wrong_kind" | "wrong_state"; detail: string };

/**
 * A steward's verdict (§4 amendment, UI-11). **Ledger state only** —
 * this function writes one row in `ledger_issues` and nothing else. It
 * makes no git call and it writes no KB content, and it never could:
 * it holds a Postgres pool and knows nothing about a repository.
 * Approve means *worth drafting*; the certification act remains a human
 * merging a reviewed diff (KB-7).
 *
 * The transition set is the §4 diagram's, verbatim: verdicts are cast
 * on `open` requests. Anything already approved, rejected, batched or
 * resolved is a conflict the caller is told about rather than a silent
 * overwrite of another steward's decision.
 */
export async function recordVerdict(
  pool: pg.Pool,
  input: { issueId: string; verdict: "approve" | "reject"; reason?: string | null; by: string; at?: Date },
): Promise<VerdictOutcome> {
  const existing = await getIssue(pool, input.issueId);
  if (!existing) return { ok: false, code: "not_found", detail: `no issue ${input.issueId}` };
  if (existing.kind !== ENRICHMENT_REQUEST) {
    return {
      ok: false,
      code: "wrong_kind",
      detail: `verdicts apply to ${ENRICHMENT_REQUEST} issues only; ${input.issueId} is ${existing.kind}`,
    };
  }
  if (existing.status !== "open") {
    return {
      ok: false,
      code: "wrong_state",
      detail: `issue ${input.issueId} is ${existing.status}; verdicts are cast on open requests`,
    };
  }
  const reason = input.reason ? scrubText(input.reason, VERDICT_REASON_MAX) : null;
  const { rows } = await pool.query<{ issue_id: string }>(
    `UPDATE ledger_issues
        SET status = $2, verdict_by = $3, verdict_at = $4, verdict_reason = $5
      WHERE issue_id = $1::uuid AND status = 'open' AND kind = $6
      RETURNING issue_id`,
    [
      input.issueId,
      input.verdict === "approve" ? "approved" : "rejected",
      input.by,
      input.at ?? new Date(),
      reason,
      ENRICHMENT_REQUEST,
    ],
  );
  if (!rows[0]) {
    return { ok: false, code: "wrong_state", detail: `issue ${input.issueId} changed state concurrently` };
  }
  return { ok: true, issue: (await getIssue(pool, input.issueId))! };
}

/**
 * A steward's triage act on a **non-request** issue (§7's lifecycle,
 * §8's one-click actions).
 *
 * `enrichment_request` runs the §4 verdict lifecycle instead and is
 * refused here — the two must not be reachable from one another, because
 * "approve" on a request means *worth drafting* while "acknowledge" on a
 * gap means *this is real, work it*, and collapsing them would let a
 * request skip its verdict.
 *
 * What the two actions mean, said once so the UI can quote it:
 *
 * - **acknowledge** (`open → triaged`): a human has seen this and it is
 *   worth working. It is not a fix and it claims nothing about one — but
 *   it *is* the signal the enrich skill's S1 reads, so a triaged gap is
 *   on somebody's work list rather than in a pile.
 * - **dismiss** (`open|triaged → dismissed`): not worth doing, with a
 *   reason. The row is kept, not deleted — the record of what was
 *   declined is worth as much as the record of what was done, and L-4
 *   reopens it if the same gap recurs, which is exactly the argument for
 *   revisiting a `wont_fix` that eleven more people hit.
 *
 * The reason is stored on `resolution` beside a resolution's own payload
 * rather than in a new column: both are "how this issue reached a
 * terminal state, and who decided", and one shape for that is one place
 * to read it.
 */
export async function recordTriage(
  pool: pg.Pool,
  input: { issueId: string; action: "acknowledge" | "dismiss"; reason?: string | null; by: string; at?: Date },
): Promise<VerdictOutcome> {
  const existing = await getIssue(pool, input.issueId);
  if (!existing) return { ok: false, code: "not_found", detail: `no issue ${input.issueId}` };
  if (existing.kind === ENRICHMENT_REQUEST) {
    return {
      ok: false,
      code: "wrong_kind",
      detail:
        `${input.issueId} is a knowledge request; it runs the approve/reject verdict lifecycle ` +
        "(fault-ledger §4), not gap triage",
    };
  }
  const from = input.action === "acknowledge" ? ["open"] : ["open", "triaged"];
  if (!from.includes(existing.status)) {
    return {
      ok: false,
      code: "wrong_state",
      detail: `issue ${input.issueId} is ${existing.status}; ${input.action} applies to ${from.join(" or ")}`,
    };
  }

  if (input.action === "acknowledge") {
    const { rows } = await pool.query<{ issue_id: string }>(
      `UPDATE ledger_issues SET status = 'triaged'
        WHERE issue_id = $1::uuid AND status = 'open' RETURNING issue_id`,
      [input.issueId],
    );
    if (!rows[0]) {
      return { ok: false, code: "wrong_state", detail: `issue ${input.issueId} changed state concurrently` };
    }
    return { ok: true, issue: (await getIssue(pool, input.issueId))! };
  }

  // LED-R2 binds the reason: it is human-authored text a later reader
  // sees, exactly as a rejection reason is.
  const reason = scrubText(input.reason ?? "", VERDICT_REASON_MAX);
  const { rows } = await pool.query<{ issue_id: string }>(
    `UPDATE ledger_issues
        SET status = 'dismissed', resolved_at = $3, resolved_by = $2,
            resolution = jsonb_build_object('kind', 'dismissed', 'reason', $4::text, 'by', $2::text)
      WHERE issue_id = $1::uuid AND status = ANY($5) RETURNING issue_id`,
    [input.issueId, input.by, input.at ?? new Date(), reason, from],
  );
  if (!rows[0]) {
    return { ok: false, code: "wrong_state", detail: `issue ${input.issueId} changed state concurrently` };
  }
  return { ok: true, issue: (await getIssue(pool, input.issueId))! };
}

/**
 * Hand a batched request back to the queue (§4: `batched → approved`,
 * "returns with the skill's note").
 *
 * The transition the state diagram drew and nothing implemented until
 * B-1. It exists so the enrich skill has somewhere honest to put a
 * request it cannot draft: the alternative to a mechanism here is a
 * guess in a document, which is the one outcome CP-E5 forbids.
 *
 * `batch_id` is cleared, so the next batch can pick it up — a returned
 * request is approved work waiting for evidence, not failed work. The
 * verdict columns are untouched: the steward's approval still stands,
 * because nothing about it turned out to be wrong.
 *
 * Occurrences are deliberately NOT incremented. The queue is ordered by
 * demand, and a skill reporting that it could not write something is not
 * another person asking for it.
 */
export async function returnToQueue(
  pool: pg.Pool,
  input: { issueId: string; note: string; at?: Date },
): Promise<VerdictOutcome> {
  const existing = await getIssue(pool, input.issueId);
  if (!existing) return { ok: false, code: "not_found", detail: `no issue ${input.issueId}` };
  if (existing.kind !== ENRICHMENT_REQUEST) {
    return {
      ok: false,
      code: "wrong_kind",
      detail: `only ${ENRICHMENT_REQUEST} issues are returned to the queue; ${input.issueId} is ${existing.kind}`,
    };
  }
  if (existing.status !== "batched") {
    return {
      ok: false,
      code: "wrong_state",
      detail: `issue ${input.issueId} is ${existing.status}; only a batched request can be returned`,
    };
  }
  // LED-R2: the note is shown to a steward and reaches the filer's reply
  // path, so it is scrubbed and bounded exactly as a rejection reason is.
  const note = scrubText(input.note, VERDICT_REASON_MAX);
  const { rows } = await pool.query<{ issue_id: string }>(
    `UPDATE ledger_issues
        SET status = 'approved', batch_id = NULL, return_note = $2, returned_at = $3
      WHERE issue_id = $1::uuid AND status = 'batched' AND kind = $4
      RETURNING issue_id`,
    [input.issueId, note, input.at ?? new Date(), ENRICHMENT_REQUEST],
  );
  if (!rows[0]) {
    return { ok: false, code: "wrong_state", detail: `issue ${input.issueId} changed state concurrently` };
  }
  return { ok: true, issue: (await getIssue(pool, input.issueId))! };
}

/**
 * The "deliver batch" trigger (§8): stamp up to `max` approved requests
 * with one batch id and move them to `batched`. This hands the enrich
 * skill a scoped work list — it does not draft, and it does not open a
 * PR. Resolution rides the existing L-5 CL-Resolves lifecycle when the
 * human merges the batch PR's reviewed diff.
 *
 * Bounded at ~10 by config so no batch becomes an immortal rolling PR.
 */
export async function deliverBatch(
  pool: pg.Pool,
  input: { max: number; by: string },
): Promise<{ batchId: string; issues: TriageIssue[] }> {
  const batchId = `batch-${randomUUID()}`;
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const { rows } = await client.query<{ issue_id: string }>(
      `UPDATE ledger_issues
          SET status = 'batched', batch_id = $1
        WHERE issue_id IN (
          SELECT issue_id FROM ledger_issues
           WHERE kind = $2 AND status = 'approved' AND batch_id IS NULL
           ORDER BY occurrences DESC, distinct_subjects DESC, last_seen DESC, issue_id DESC
           LIMIT $3
           FOR UPDATE SKIP LOCKED)
        RETURNING issue_id`,
      [batchId, ENRICHMENT_REQUEST, Math.max(1, input.max)],
    );
    await client.query("COMMIT");
    const issues: TriageIssue[] = [];
    for (const row of rows) {
      const issue = await getIssue(pool, row.issue_id);
      if (issue) issues.push(issue);
    }
    return { batchId, issues };
  } catch (err) {
    await client.query("ROLLBACK").catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

// ---------------------------------------------------------------------------
// Class-1 detector rules (§5) — config-driven (L-3)

export interface DetectorRule {
  rule: string;
  enabled: boolean;
  config: Record<string, unknown>;
}

export async function loadRules(pool: pg.Pool): Promise<Map<string, DetectorRule>> {
  const { rows } = await pool.query<{ rule: string; enabled: boolean; config: Record<string, unknown> }>(
    `SELECT rule, enabled, config FROM detector_rules`,
  );
  return new Map(rows.map((r) => [r.rule, r]));
}

/**
 * Window rules over the audit stream (§5): repeated_validate_fail and
 * guardrail_pattern. Idempotent per sweep: a fingerprint gets a new
 * event only when qualifying audit records arrived after its last one.
 */
export async function sweepWindowRules(pool: pg.Pool): Promise<number> {
  const rules = await loadRules(pool);
  let emitted = 0;

  const validateRule = rules.get("repeated_validate_fail");
  if (validateRule?.enabled) {
    const threshold = Number(validateRule.config.threshold ?? 3);
    const windowH = Number(validateRule.config.window_h ?? 24);
    const { rows } = await pool.query<{ object_fqn: string; n: string; latest: Date; system: string | null }>(
      `SELECT obj AS object_fqn, count(*) AS n, max(ts) AS latest,
              min(split_part(obj, '.', 1)) AS system
         FROM audit_records,
              jsonb_array_elements_text(result_meta->'cited_objects') AS obj
        WHERE tool = 'validate_sql'
          AND result_meta->>'verdict' = 'fail'
          AND ts > now() - make_interval(hours => $1)
        GROUP BY obj
       HAVING count(*) >= $2`,
      [windowH, threshold],
    );
    for (const row of rows) {
      const fingerprint = fingerprintOf("doc_schema_mismatch", row.object_fqn);
      const { rows: last } = await pool.query<{ ts: Date }>(
        `SELECT max(ts) AS ts FROM ledger_events WHERE fingerprint = $1 AND detector_class = 1`,
        [fingerprint],
      );
      if (last[0]?.ts && last[0].ts >= row.latest) continue;
      await recordEvent(pool, {
        detectorClass: 1,
        kind: "doc_schema_mismatch",
        scope: row.object_fqn,
        system: row.system,
        objectFqn: row.object_fqn,
        detail: { rule: "repeated_validate_fail", failures: Number(row.n) },
      });
      emitted += 1;
    }
  }

  const guardrailRule = rules.get("guardrail_pattern");
  if (guardrailRule?.enabled) {
    const threshold = Number(guardrailRule.config.threshold ?? 3);
    const windowH = Number(guardrailRule.config.window_h ?? 24);
    const codes = Array.isArray(guardrailRule.config.codes)
      ? (guardrailRule.config.codes as string[])
      : ["timeout", "row_cap", "quota_exhausted"];
    const { rows } = await pool.query<{ system: string; code: string; n: string; latest: Date }>(
      `SELECT result_meta->>'system' AS system, result_meta->>'guardrail_code' AS code,
              count(*) AS n, max(ts) AS latest
         FROM audit_records
        WHERE tool IN ('execute_sql', 'publish_report')
          AND result_meta->>'guardrail_code' = ANY($1)
          AND ts > now() - make_interval(hours => $2)
        GROUP BY 1, 2
       HAVING count(*) >= $3`,
      [codes, windowH, threshold],
    );
    for (const row of rows) {
      const scope = `${row.system}:${row.code}`;
      const fingerprint = fingerprintOf("guardrail_hit", scope);
      const { rows: last } = await pool.query<{ ts: Date }>(
        `SELECT max(ts) AS ts FROM ledger_events WHERE fingerprint = $1 AND detector_class = 1`,
        [fingerprint],
      );
      if (last[0]?.ts && last[0].ts >= row.latest) continue;
      await recordEvent(pool, {
        detectorClass: 1,
        kind: "guardrail_hit",
        scope,
        system: row.system,
        detail: { rule: "guardrail_pattern", code: row.code, terminations: Number(row.n) },
      });
      emitted += 1;
    }
  }

  return emitted;
}

/** §10 retention: events beyond the horizon are deleted, issues never. */
export async function sweepRetention(pool: pg.Pool, retentionDays: number): Promise<number> {
  const { rowCount } = await pool.query(
    `DELETE FROM ledger_events WHERE ts < now() - make_interval(days => $1)`,
    [retentionDays],
  );
  return rowCount ?? 0;
}

// ---------------------------------------------------------------------------
// Loop closure (L-5, LED-R4): merged PRs carrying CL-Resolves trailers

const TRAILER_RE = /^CL-Resolves:\s*([0-9a-fA-F-]{36})\s*$/gm;

export function parseResolveTrailers(body: string): string[] {
  return [...body.matchAll(TRAILER_RE)].map((m) => m[1]!.toLowerCase());
}

export async function sweepResolutions(pool: pg.Pool, provider: PrProvider): Promise<number> {
  const { rows } = await pool.query<{ value: { cursor: string } }>(
    `SELECT value FROM mcp_state WHERE key = 'resolve_cursor'`,
  );
  const cursor = rows[0]?.value?.cursor ?? null;
  let merged: MergedPr[];
  try {
    merged = await provider.listMergedPrs(cursor);
  } catch {
    return 0; // provider unreachable; next sweep retries from the cursor
  }
  let resolved = 0;
  let maxMergedAt = cursor ?? "";
  for (const pr of merged) {
    if (pr.mergedAt > maxMergedAt) maxMergedAt = pr.mergedAt;
    for (const issueId of parseResolveTrailers(pr.body)) {
      // LED-R4: the issue must exist; merge authority is the KB's own
      // branch protection (D-47) — a merged PR is the credential.
      const { rowCount } = await pool.query(
        `UPDATE ledger_issues
            SET status = 'resolved', resolved_at = $2, resolved_by = 'pr',
                resolution = jsonb_build_object('kind', 'enrichment_pr', 'pr_url', $3::text),
                links = jsonb_set(links, '{prs}',
                        coalesce(links->'prs', '[]'::jsonb) || to_jsonb($3::text))
          WHERE issue_id = $1 AND status <> 'resolved'`,
        [issueId, pr.mergedAt, pr.url],
      );
      if (rowCount) resolved += 1;
    }
  }
  if (maxMergedAt && maxMergedAt !== cursor) {
    await pool.query(
      `INSERT INTO mcp_state (key, value) VALUES ('resolve_cursor', $1)
       ON CONFLICT (key) DO UPDATE SET value = $1, updated_at = now()`,
      [JSON.stringify({ cursor: maxMergedAt })],
    );
  }
  return resolved;
}
