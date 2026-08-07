/**
 * Fault ledger through the MCP surface (fault-ledger spec, FL-E
 * checklist): flag_gap/list_gaps with server-set identity (LED-R3),
 * steward gating (LED-R1/FL-5), storage scrub + visibility + length
 * bounds (LED-R2), render neutralization (LED-R5), CL-Resolves loop
 * closure + recurrence reopen (LED-R4/FL-4/FL-10), retention (LED-R6/
 * FL-7), counts-only subjects (LED-R7), and the MT-7 class-1 detectors.
 */

import { readFile, writeFile } from "node:fs/promises";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createProvider } from "../src/gitkb.js";
import { sweepResolutions, sweepRetention, sweepWindowRules } from "../src/ledger.js";
import { syncConfig } from "./sync-helpers.js";
import {
  auditRows,
  callTool,
  listTools,
  setupMcpRig,
  USERS,
  type McpRig,
} from "./mcp-helpers.js";

let rig: McpRig;

beforeAll(async () => {
  rig = await setupMcpRig();
}, 240_000);

afterAll(async () => {
  await rig.stop();
});

async function issueRow(issueId: string): Promise<Record<string, unknown>> {
  const { rows } = await rig.core.pool.query(`SELECT * FROM ledger_issues WHERE issue_id = $1`, [issueId]);
  return rows[0]!;
}

describe("flag_gap — class-2 ingestion (§6, L-6, LED-R3)", () => {
  it("LED-R3: identity/session/profile/refs are server-set; client-supplied subject is ignored", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "missing_doc",
      description: "no doc explains the orders lifecycle",
      object: "drill.shop.orders",
      subject: "evil-forged-subject",
      refs: { kb_ref: "forged" },
    });
    expect(result.isError).toBe(false);
    expect(typeof result.payload.issue_id).toBe("string");
    expect(result.payload.routed_to).toBe("data-team");
    const { rows } = await rig.core.pool.query(
      `SELECT * FROM ledger_events WHERE issue_id = $1 ORDER BY ts DESC`,
      [result.payload.issue_id],
    );
    const event = rows[0]!;
    expect(event.subject).toBe(USERS.reporter.username);
    expect(event.profile).toBe("reporter");
    expect(event.detector_class).toBe(2);
    expect(event.audit_ref).toBeTruthy();
    expect(String(event.kb_ref)).toMatch(/^[0-9a-f]{40}$/);
    // The audit_ref points at the flag_gap call's own audit record (L-8).
    const audits = await auditRows(rig, { tool: "flag_gap" });
    expect(audits.some((a) => a.audit_id === event.audit_ref)).toBe(true);
  });

  it("L-6: the same gap flagged again dedups into one issue with occurrence + distinct-subject counts", async () => {
    const again = await callTool(rig, rig.token("steward"), "steward", "flag_gap", {
      kind: "missing_doc",
      description: "orders lifecycle undocumented (steward hit it too)",
      object: "drill.shop.orders",
    });
    expect(again.payload.occurrences).toBe(2);
    const issue = await issueRow(again.payload.issue_id as string);
    expect(issue.occurrences).toBe(2);
    expect(issue.distinct_subjects).toBe(2);
  });
});

describe("FL-5 / LED-R1 — list_gaps gating", () => {
  it("FL-5: list_gaps absent from reporter tools/list, present for steward; direct call denied", async () => {
    const reporter = await listTools(rig, rig.token("reporter"), "reporter");
    expect(reporter.names).not.toContain("list_gaps");
    const steward = await listTools(rig, rig.token("steward"), "steward");
    expect(steward.names).toContain("list_gaps");
    const denied = await callTool(rig, rig.token("reporter"), "reporter", "list_gaps", {});
    expect(denied.payload.code).toBe("permission_denied");
  });

  it("FL-5 / LED-R2: issues attributed to objects outside the caller's visibility are omitted", async () => {
    await callTool(rig, rig.token("steward"), "steward", "flag_gap", {
      kind: "uncertified_metric",
      description: "net sales rollup lacks certification evidence",
      object: "drill.reporting.v_net_sales",
    });
    const full = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {});
    const fullFqns = (full.payload.issues as { object_fqn?: string }[]).map((i) => i.object_fqn);
    expect(fullFqns).toContain("drill.reporting.v_net_sales");

    // aud-lite holds the steward profile through a shop-only role (KB-A).
    const lite = await callTool(rig, rig.token("auditlite"), "steward", "list_gaps", {});
    expect(lite.isError).toBe(false);
    const liteFqns = (lite.payload.issues as { object_fqn?: string }[]).map((i) => i.object_fqn);
    expect(liteFqns).not.toContain("drill.reporting.v_net_sales");
    expect(liteFqns).toContain("drill.shop.orders");
  });

  it("LED-R7: distinct_subjects is a count, and the only identity in the response is the author of the filing it returns", async () => {
    const result = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {});
    const issues = result.payload.issues as {
      distinct_subjects: unknown;
      filing: { by: string | null } | null;
    }[];
    const issue = issues[0]!;
    expect(typeof issue.distinct_subjects).toBe("number");

    // The rule as D-116.5 scopes it: `distinct_subjects` names nobody,
    // and an identity appears only where it is the recorded author of
    // text in the same response. The dashboard's issue view has shown a
    // steward that same subject since D-114; `list_gaps` was the surface
    // that disagreed. Every name in the payload must be one of those
    // authors — a subject appearing anywhere else is the leak this
    // asserts against.
    const authors = new Set(issues.map((i) => i.filing?.by).filter(Boolean));
    for (const username of [USERS.reporter.username, USERS.steward.username]) {
      if (JSON.stringify(result.payload).includes(username)) {
        expect(authors).toContain(username);
      }
    }
    // And the aggregate is never decorated with the people behind it.
    for (const i of issues) {
      expect(Object.keys(i)).not.toContain("subjects");
    }
  });
});

describe("LED-R2 / FL-6 — storage scrub: data values never land in the ledger", () => {
  it("MT-7 + LED-R2: a zero-result search opens a coverage_gap whose stored terms carry no PII literals", async () => {
    const result = await callTool(rig, rig.token("reporter"), "reporter", "search_context", {
      query: "salary for ssn 123-45-6789 of bob@example.com xzzqy",
    });
    expect((result.payload.results as unknown[]).length).toBe(0);
    const { rows } = await rig.core.pool.query(
      `SELECT i.title, e.description FROM ledger_issues i
         JOIN ledger_events e ON e.issue_id = i.issue_id
        WHERE i.kind = 'coverage_gap' ORDER BY e.ts DESC`,
    );
    expect(rows.length).toBeGreaterThan(0);
    const text = JSON.stringify(rows);
    expect(text).not.toContain("123-45-6789");
    expect(text).not.toContain("bob@example.com");
    expect(rows[0]!.title).toContain("coverage_gap");
  });

  it("FL-6: a canary secret in a flag description is scrubbed from the ledger; audit keeps only the args digest", async () => {
    const canary = "SECRETVALUE12345678";
    const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "other",
      description: `the connection string 'postgres://u:${canary}@db/x' fails against ${canary}`,
    });
    expect(result.isError).toBe(false);
    const { rows } = await rig.core.pool.query(
      `SELECT description, detail FROM ledger_events WHERE issue_id = $1`,
      [result.payload.issue_id],
    );
    expect(JSON.stringify(rows)).not.toContain(canary);
    const audits = await auditRows(rig, { tool: "flag_gap" });
    for (const audit of audits) {
      expect(audit.statement_text).toBeNull(); // full text only for validate
      expect(String(audit.args_digest)).toMatch(/^[0-9a-f]{64}$/);
    }
  });

  it("LED-R2: titles are length-bounded", async () => {
    const long = "needs docs ".repeat(60);
    const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "missing_entity",
      description: long,
    });
    const issue = await issueRow(result.payload.issue_id as string);
    expect(String(issue.title).length).toBeLessThanOrEqual(160);
  });

  it("LED-R5: ledger text renders inert in list_gaps (neutralized at the render point)", async () => {
    await callTool(rig, rig.token("steward"), "steward", "flag_gap", {
      kind: "missing_doc",
      description: "gap with markdown hazards",
      object: "drill.shop.`evil`@table[x]*y",
    });
    const result = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {});
    const hazard = (result.payload.issues as { title: string }[]).find((i) => i.title.includes("evil"));
    expect(hazard).toBeDefined();
    expect(hazard!.title).not.toContain("`");
    expect(hazard!.title).not.toContain("@");
    expect(hazard!.title).not.toContain("[");
  });
});

describe("MT-7 — class-1 detectors fire without agent cooperation (§5, L-3)", () => {
  it("repeated validate failures against one object open a doc_schema_mismatch issue via the window rule", async () => {
    for (let i = 0; i < 3; i += 1) {
      const result = await callTool(rig, rig.token("reporter"), "reporter", "validate_sql", {
        system: "drill",
        request: { dialect: "sql", statement: `SELECT dropped_col_${i} FROM shop.order_items` },
      });
      expect(result.payload.verdict).toBe("fail");
    }
    const emitted = await sweepWindowRules(rig.core.pool);
    expect(emitted).toBeGreaterThan(0);
    const { rows } = await rig.core.pool.query(
      `SELECT * FROM ledger_issues WHERE kind = 'doc_schema_mismatch' AND object_fqn = 'drill.shop.order_items'`,
    );
    expect(rows.length).toBe(1);
    const again = await sweepWindowRules(rig.core.pool);
    expect(again).toBe(0); // idempotent until new failures arrive
  });
});

describe("FL-4 / LED-R4 — CL-Resolves loop closure; FL-10 recurrence reopen (L-4/L-5)", () => {
  it("FL-4: a merged PR carrying CL-Resolves resolves the issue with pr_url; recurrence reopens it", async () => {
    const flagged = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "missing_join_path",
      description: "no documented join from orders to customers",
      object: "drill.shop.order_items",
    });
    const issueId = flagged.payload.issue_id as string;

    // Merge a PR carrying the trailer (local provider store, the same
    // pipeline shape as the GitHub provider).
    const store = {
      next: 2,
      prs: [
        {
          number: 1,
          url: "local-pr://1",
          branch: "enrich/join-paths",
          title: "enrich: join paths",
          body: `Documents the join.\n\nCL-Resolves: ${issueId}\n`,
          labels: [],
          state: "merged",
          merged_at: new Date().toISOString(),
          comments: [],
        },
      ],
    };
    await writeFile(rig.kb.prsFile, JSON.stringify(store, null, 2));
    const provider = createProvider(syncConfig(rig.kb, `${rig.kb.remote}-wd`));
    const resolved = await sweepResolutions(rig.core.pool, provider);
    expect(resolved).toBe(1);
    let issue = await issueRow(issueId);
    expect(issue.status).toBe("resolved");
    expect(issue.resolved_by).toBe("pr");
    expect((issue.resolution as { pr_url: string }).pr_url).toBe("local-pr://1");

    // LED-R4/L-4: a matching event after resolution reopens with the
    // resolution history preserved.
    const recurrence = await callTool(rig, rig.token("steward"), "steward", "flag_gap", {
      kind: "missing_join_path",
      description: "join still undocumented after the PR",
      object: "drill.shop.order_items",
    });
    expect(recurrence.payload.issue_id).toBe(issueId);
    issue = await issueRow(issueId);
    expect(issue.status).toBe("open");
    expect(issue.reopen_count).toBe(1);
    expect((issue.resolution as { pr_url: string }).pr_url).toBe("local-pr://1"); // preserved (LED-R6)
  });

  it("FL-10: a dismissed issue reoccurring reopens with the counter incremented", async () => {
    const flagged = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "capability_gap",
      description: "cannot express weekly cohort retention",
    });
    const issueId = flagged.payload.issue_id as string;
    await rig.core.pool.query(`UPDATE ledger_issues SET status = 'dismissed' WHERE issue_id = $1`, [issueId]);
    const again = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "capability_gap",
      description: "cannot express weekly cohort retention",
    });
    expect(again.payload.issue_id).toBe(issueId);
    const issue = await issueRow(issueId);
    expect(issue.status).toBe("open");
    expect(issue.reopen_count).toBe(1);
  });
});

describe("FL-7 / LED-R6 — retention deletes events, never issues", () => {
  it("FL-7: the sweep removes >90d events and leaves issues + resolution history intact", async () => {
    const flagged = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
      kind: "missing_doc",
      description: "ancient gap for retention",
      object: "drill.shop.customers",
    });
    const issueId = flagged.payload.issue_id as string;
    await rig.core.pool.query(
      `UPDATE ledger_events SET ts = now() - interval '100 days' WHERE issue_id = $1`,
      [issueId],
    );
    const before = await rig.core.pool.query(`SELECT count(*) AS n FROM ledger_issues`);
    const deleted = await sweepRetention(rig.core.pool, 90);
    expect(deleted).toBeGreaterThan(0);
    const after = await rig.core.pool.query(`SELECT count(*) AS n FROM ledger_issues`);
    expect(after.rows[0].n).toBe(before.rows[0].n);
    const issue = await issueRow(issueId);
    expect(issue.occurrences).toBe(1); // the issue survives its events
  });
});
