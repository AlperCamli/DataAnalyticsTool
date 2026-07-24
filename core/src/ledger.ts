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
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    const routedTo = await routeFor(client, input.kind);
    const { rows } = await client.query<{ issue_id: string; occurrences: number }>(
      `INSERT INTO ledger_issues
         (issue_id, fingerprint, kind, system, object_fqn, title, routed_to,
          first_seen, last_seen, occurrences, distinct_subjects)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, 1, 0)
       ON CONFLICT (fingerprint) DO UPDATE SET
         occurrences = ledger_issues.occurrences + 1,
         last_seen   = EXCLUDED.last_seen,
         reopen_count = CASE WHEN ledger_issues.status IN ('resolved','dismissed')
                             THEN ledger_issues.reopen_count + 1
                             ELSE ledger_issues.reopen_count END,
         status      = CASE WHEN ledger_issues.status IN ('resolved','dismissed')
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
        JSON.stringify(input.detail ?? {}),
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
