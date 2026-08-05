/**
 * `extract-audit.sh` is a client of the §5 read APIs (B-0 deliverable 3).
 *
 * The proof that the retirement of its direct-DB path cost nothing is
 * mechanical rather than asserted: the CP-7 gate's own committed
 * evidence is loaded back into a scratch database, the *same script the
 * runbook invokes* is run over the same window, and its output is diffed
 * against the committed files byte for byte.
 *
 * One column is expected to differ, and the test states exactly which
 * and why: §5.3 requires the ledger read to serve LED-R5-neutralized
 * text, which the retired psql dump — reading the raw column — did not
 * do. That divergence is the spec being enforced, so the test asserts it
 * precisely (neutralize(committed) === extracted) rather than waiving
 * the file.
 */

import { execFile } from "node:child_process";
import { copyFileSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { setupDashboardRig, type DashboardRig } from "./dashboard-helpers.js";
import { pythonPath, repoRoot } from "./helpers.js";
import { neutralize } from "../src/changelog.js";

const GATE = path.join(repoRoot(), "results", "cp7-gate");
/** The instant EVIDENCE-2026-07-29.md records for this extraction. */
const SINCE = "2026-07-29T11:00:00Z";

const committed = (name: string) => readFileSync(path.join(GATE, name), "utf-8");

interface AuditRow {
  audit_id: string;
  ts: string;
  subject: string;
  roles: string[];
  profile: string | null;
  session_id: string | null;
  tool: string;
  args_digest: string;
  kb_ref: string | null;
  snapshot_ref: Record<string, string> | null;
  decision: string;
  decision_reason: string | null;
  duration_ms: number | null;
  result_meta: Record<string, unknown>;
  statement_text: string | null;
}

/** Split a `psql -At -F'|'` line whose free-text column sits at `textAt`
 * with `tail` fixed fields after it. */
function splitRow(line: string, textAt: number, tail: number): string[] {
  const head = line.split("|");
  const before = head.slice(0, textAt);
  const after = head.slice(head.length - tail);
  const text = head.slice(textAt, head.length - tail).join("|");
  return [...before, text, ...after];
}

describe("extract-audit.sh over the §5 read APIs", () => {
  let rig: DashboardRig;
  let out: string;

  beforeAll(async () => {
    rig = await setupDashboardRig();

    // -- reload the committed gate evidence into a scratch estate -----------
    const audit = JSON.parse(committed("audit-chain.json")) as AuditRow[];
    for (const row of audit) {
      await rig.core.pool.query(
        `INSERT INTO audit_records
           (audit_id, ts, subject, roles, profile, session_id, tool, args_digest,
            kb_ref, snapshot_ref, decision, decision_reason, duration_ms,
            result_meta, statement_text)
         VALUES ($1,$2::timestamptz,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`,
        [
          row.audit_id, row.ts, row.subject, row.roles, row.profile, row.session_id,
          row.tool, row.args_digest, row.kb_ref,
          row.snapshot_ref === null ? null : JSON.stringify(row.snapshot_ref),
          row.decision, row.decision_reason, row.duration_ms,
          JSON.stringify(row.result_meta), row.statement_text,
        ],
      );
    }

    // ledger-events.txt: ts|class|kind|system|fqn|subject|audit_ref|description|status|routed_to
    const events = committed("ledger-events.txt").split("\n").filter(Boolean);
    for (const [index, raw] of events.entries()) {
      const [ts, cls, kind, system, fqn, subject, auditRef, description, status, routedTo] =
        splitRow(raw, 7, 2) as string[];
      const { rows } = await rig.core.pool.query<{ issue_id: string }>(
        `INSERT INTO ledger_issues
           (fingerprint, kind, system, object_fqn, title, status, routed_to,
            first_seen, last_seen, occurrences, distinct_subjects)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8::timestamptz,$8::timestamptz,1,1)
         RETURNING issue_id`,
        [`fp-${index}`, kind, system || null, fqn === "-" ? null : fqn, `${kind}: ${fqn}`, status, routedTo, ts],
      );
      await rig.core.pool.query(
        `INSERT INTO ledger_events
           (ts, detector_class, kind, fingerprint, system, object_fqn, subject,
            audit_ref, description, issue_id)
         VALUES ($1::timestamptz,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
        [
          ts, Number(cls), kind, `fp-${index}`, system || null,
          fqn === "-" ? null : fqn, subject || null,
          auditRef === "-" ? null : auditRef, description || null, rows[0]!.issue_id,
        ],
      );
    }

    // publish-trail.txt's delivery + attestation sections.
    const trail = committed("publish-trail.txt").split("\n");
    let section = "";
    for (const raw of trail) {
      if (raw.startsWith("-- ")) {
        section = raw;
        continue;
      }
      if (!raw.trim()) continue;
      const f = raw.split("|");
      if (section.startsWith("-- model_deliveries")) {
        await rig.core.pool.query(
          `INSERT INTO model_deliveries
             (artifact_id, target, revision, content_hash, workspace_id, dataset_id,
              tables, results, delivered_at)
           VALUES ($1,$2,$3,'reseeded',$4,$5,'[]'::jsonb,'{}'::jsonb,$6::timestamptz)`,
          [f[0], f[1], Number(f[2]), f[3], f[4], f[5]],
        );
      } else if (section.startsWith("-- report_attestations")) {
        await rig.core.pool.query(
          `INSERT INTO report_attestations
             (artifact_id, target, revision, workspace_id, dataset_id, report_id,
              definition_hash, verified_at, attested_at)
           VALUES ($1,$2,$3,'reseeded','reseeded',$4,$5,$6::timestamptz,$7::timestamptz)`,
          [f[0], f[1], Number(f[2]), f[3], f[4], f[5], f[6]],
        );
      }
    }

    // -- run the runbook's script, in a scratch directory -------------------
    out = mkdtempSync(path.join(tmpdir(), "cl-extract-"));
    const script = path.join(out, "extract-audit.sh");
    copyFileSync(path.join(GATE, "extract-audit.sh"), script);
    // Async on purpose: the core under test is listening in *this*
    // process, so a synchronous child would block the event loop that
    // has to answer the script's own HTTP calls.
    await promisify(execFile)("bash", [script, SINCE], {
      encoding: "utf-8",
      env: {
        ...process.env,
        CL_API: rig.base,
        CL_TOKEN: rig.token("steward"),
        CL_PYTHON: pythonPath(),
      },
    });
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  const extracted = (name: string) => readFileSync(path.join(out, name), "utf-8");

  it("holds no database credential and no direct-DB path", () => {
    const script = committed("extract-audit.sh");
    expect(script).not.toContain("psql");
    expect(script).not.toContain("docker exec");
    expect(script).not.toContain("CORE_DATABASE_URL");
    expect(script).toContain("/v1/dashboard/audit");
  });

  /**
   * PA-3 (D-108.4) added one audit column *after* this evidence was
   * written, so a fresh extraction now carries one field the committed
   * files could not have. The evidence is not rewritten to match — it is
   * the record of what was extracted then. Instead the relationship is
   * stated exactly: strip the one new field and the reproduction is
   * still byte for byte, and the stripped field is `-` on every row,
   * which is what the column means for rows that predate it.
   */
  const withoutStamp = (text: string) =>
    text
      .split("\n")
      .map((line) => (line ? line.slice(0, line.lastIndexOf("|")) : line))
      .join("\n");

  it("reproduces audit-chain.txt byte for byte, but for PA-3's added field", () => {
    expect(withoutStamp(extracted("audit-chain.txt"))).toBe(committed("audit-chain.txt"));
    for (const line of extracted("audit-chain.txt").split("\n").filter(Boolean)) {
      // NULL, not `unstamped`: these rows predate the column, which is a
      // different statement from "the session presented no stamp".
      expect(line.slice(line.lastIndexOf("|") + 1)).toBe("-");
    }
  });

  /** The JSON files gain one key per row for the same reason. */
  const stripStamp = (text: string) =>
    (JSON.parse(text) as Record<string, unknown>[]).map((row) => {
      expect(Object.hasOwn(row, "setup_stamp")).toBe(true);
      expect(row.setup_stamp).toBeNull();
      const { setup_stamp: _dropped, ...rest } = row;
      return rest;
    });

  it("reproduces audit-chain.json, but for PA-3's added key", () => {
    expect(stripStamp(extracted("audit-chain.json"))).toEqual(
      JSON.parse(committed("audit-chain.json")),
    );
  });

  it("reproduces publish-results.json, but for PA-3's added key", () => {
    expect(stripStamp(extracted("publish-results.json"))).toEqual(
      JSON.parse(committed("publish-results.json")),
    );
  });

  it("reproduces publish-trail.txt byte for byte, dangling section included", () => {
    expect(extracted("publish-trail.txt")).toBe(committed("publish-trail.txt"));
  });

  /**
   * The ledger file reproduces exactly for *this* evidence, and the
   * assertion below says why that is not a coincidence: §5.3 makes the
   * governed read serve LED-R5-neutralized text, and neutralization is
   * the identity function on descriptions that carry no markdown or HTML
   * metacharacters — which the CP-7 descriptions do not. An extraction
   * whose ledger text *did* carry them would differ from a raw column
   * dump here, correctly, and the per-column check states exactly where.
   */
  it("reproduces ledger-events.txt, with ledger text served LED-R5-neutralized", () => {
    const before = committed("ledger-events.txt").split("\n").filter(Boolean);
    const after = extracted("ledger-events.txt").split("\n").filter(Boolean);
    expect(after).toHaveLength(before.length);

    for (const [index, line] of before.entries()) {
      const committedFields = splitRow(line, 7, 2);
      const extractedFields = splitRow(after[index]!, 7, 2);
      for (const column of [0, 1, 2, 3, 4, 5, 6, 8, 9]) {
        expect(extractedFields[column], `row ${index} column ${column}`).toBe(committedFields[column]);
      }
      // The description column is the neutralized rendering of what is
      // stored — here, byte-identical to it.
      expect(extractedFields[7]).toBe(neutralize(committedFields[7]!));
    }
    expect(extracted("ledger-events.txt")).toBe(committed("ledger-events.txt"));
  });

  it("pages the audit endpoint rather than trusting one response", () => {
    // The window holds more rows than a single small page, and the file
    // still carries every one of them.
    const rows = JSON.parse(committed("audit-chain.json")) as AuditRow[];
    expect(extracted("audit-chain.txt").split("\n").filter(Boolean)).toHaveLength(rows.length);
  });
});
