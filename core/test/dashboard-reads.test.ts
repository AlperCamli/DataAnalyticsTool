/**
 * B-0 governed read APIs (dashboard spec §5) — audit, publish
 * deliveries, ledger triage.
 *
 * DT-1 is the reason this file exists: for each of the three endpoints,
 * a reporter reads only their own rows, and a crafted request for
 * somebody else's is refused *server-side*. The subject is taken from
 * the resolved session; there is no request shape that makes the server
 * trust a client-supplied one.
 */

import { randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { apiGet, login, setupDashboardRig, type BrowserSession, type DashboardRig } from "./dashboard-helpers.js";
import { callTool, USERS } from "./mcp-helpers.js";

/** A publish trail as the two-call contract records it (F-5/F-15). */
async function seedDelivery(
  rig: DashboardRig,
  opts: { artifactId: string; subject: string; revision: number; attestRevisions: number[] },
): Promise<void> {
  const auditId = randomUUID();
  await rig.core.pool.query(
    `INSERT INTO audit_records (audit_id, subject, roles, profile, tool, args_digest, decision, result_meta)
     VALUES ($1, $2, '{}', 'reporter', 'publish_report', 'digest', 'allowed', '{}'::jsonb)`,
    [auditId, opts.subject],
  );
  await rig.core.pool.query(
    `INSERT INTO model_deliveries
       (artifact_id, target, revision, content_hash, workspace_id, dataset_id, tables, results, audit_ref)
     VALUES ($1, 'powerbi', $2, $3, 'ws-1', 'ds-1', '[]'::jsonb, '{}'::jsonb, $4)`,
    [opts.artifactId, opts.revision, `hash-${opts.revision}`, auditId],
  );
  for (const revision of opts.attestRevisions) {
    await rig.core.pool.query(
      `INSERT INTO report_attestations
         (artifact_id, target, revision, workspace_id, dataset_id, report_id,
          definition_hash, verified_at, audit_ref)
       VALUES ($1, 'powerbi', $2, 'ws-1', 'ds-1', $3, $4, now(), $5)`,
      [opts.artifactId, revision, `report-${revision}`, `sha256:def-${revision}`, auditId],
    );
  }
}

describe("dashboard read APIs (§5) — server-side role and subject filtering", () => {
  let rig: DashboardRig;
  let reporter: BrowserSession;
  let steward: BrowserSession;

  beforeAll(async () => {
    rig = await setupDashboardRig();

    // Audit rows for two identities, written by the real MCP path.
    await callTool(rig, rig.token("reporter"), "reporter", "report_freshness");
    await callTool(rig, rig.token("reporter"), "reporter", "search_context", { q: "customers" });
    // A denial: list_gaps is steward-gated, so this lands `denied` (M-8).
    await callTool(rig, rig.token("reporter"), "reporter", "list_gaps");
    await callTool(rig, rig.token("steward"), "steward", "report_freshness");
    await callTool(rig, rig.token("steward"), "steward", "list_gaps");

    await seedDelivery(rig, {
      artifactId: "ra-reporter-1",
      subject: USERS.reporter.username,
      revision: 2,
      attestRevisions: [1, 2],
    });
    // Delivered but never attested — the loud dangling state (F-15).
    await seedDelivery(rig, {
      artifactId: "ra-steward-1",
      subject: USERS.steward.username,
      revision: 1,
      attestRevisions: [],
    });

    reporter = await login(rig, "reporter");
    steward = await login(rig, "steward");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  // -- (a) audit -------------------------------------------------------------

  describe("audit read (§5.1, U-12)", () => {
    it("DT-1: a reporter reads only their own rows", async () => {
      const res = await apiGet(rig, reporter, "/v1/dashboard/audit?limit=200");
      expect(res.status).toBe(200);
      expect(res.json.api_version).toBe("1");
      const rows = res.json.rows as { subject: string }[];
      expect(rows.length).toBeGreaterThan(0);
      expect([...new Set(rows.map((r) => r.subject))]).toEqual([USERS.reporter.username]);
      expect((res.json.scope as { role_scope: string }).role_scope).toBe("self");
    });

    it("DT-1: a crafted subject for another identity is refused server-side", async () => {
      const res = await apiGet(
        rig,
        reporter,
        `/v1/dashboard/audit?subject=${encodeURIComponent(USERS.steward.username)}`,
      );
      expect(res.status).toBe(403);
      expect(res.json.error).toBe("forbidden");
    });

    it("asking for one's own subject explicitly is allowed and changes nothing", async () => {
      const res = await apiGet(
        rig,
        reporter,
        `/v1/dashboard/audit?subject=${encodeURIComponent(USERS.reporter.username)}`,
      );
      expect(res.status).toBe(200);
      const rows = res.json.rows as { subject: string }[];
      expect([...new Set(rows.map((r) => r.subject))]).toEqual([USERS.reporter.username]);
    });

    it("steward scope v1 is full read (D-102.2), not own-plus-team", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/audit?limit=200");
      expect(res.status).toBe(200);
      const subjects = new Set((res.json.rows as { subject: string }[]).map((r) => r.subject));
      expect(subjects).toContain(USERS.reporter.username);
      expect(subjects).toContain(USERS.steward.username);
      expect((res.json.scope as { role_scope: string }).role_scope).toBe("all");
    });

    it("a steward may filter to one subject", async () => {
      const res = await apiGet(
        rig,
        steward,
        `/v1/dashboard/audit?subject=${encodeURIComponent(USERS.reporter.username)}`,
      );
      expect(res.status).toBe(200);
      const subjects = new Set((res.json.rows as { subject: string }[]).map((r) => r.subject));
      expect([...subjects]).toEqual([USERS.reporter.username]);
    });

    it("denied and filtered decisions are included, with their reason (M-8/M-4)", async () => {
      const res = await apiGet(rig, reporter, "/v1/dashboard/audit?decision=denied");
      expect(res.status).toBe(200);
      const rows = res.json.rows as { tool: string; decision: string; decision_reason: string }[];
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.every((r) => r.decision === "denied")).toBe(true);
      expect(rows.some((r) => r.tool === "list_gaps" && r.decision_reason)).toBe(true);
    });

    it("filters by tool and window", async () => {
      const byTool = await apiGet(rig, reporter, "/v1/dashboard/audit?tool=report_freshness");
      expect((byTool.json.rows as { tool: string }[]).every((r) => r.tool === "report_freshness")).toBe(true);

      const future = new Date(Date.now() + 3_600_000).toISOString();
      const empty = await apiGet(rig, reporter, `/v1/dashboard/audit?since=${encodeURIComponent(future)}`);
      expect(empty.json.rows).toHaveLength(0);

      const bad = await apiGet(rig, reporter, "/v1/dashboard/audit?since=not-a-timestamp");
      expect(bad.status).toBe(400);
      expect(bad.json.error).toBe("invalid_argument");
    });

    it("rows carry the audit record as stored (args digest, refs, decision)", async () => {
      const res = await apiGet(rig, reporter, "/v1/dashboard/audit?tool=search_context");
      const row = (res.json.rows as Record<string, unknown>[])[0]!;
      for (const field of ["audit_id", "ts", "subject", "roles", "profile", "tool", "args_digest", "decision", "result_meta"]) {
        expect(row, field).toHaveProperty(field);
      }
      expect(typeof row.args_digest).toBe("string");
    });
  });

  // -- pagination (UI-B) -----------------------------------------------------

  describe("pagination bounds (UI-B)", () => {
    it("defaults to the server page size and caps an over-large request", async () => {
      const dflt = await apiGet(rig, steward, "/v1/dashboard/audit");
      expect((dflt.json.page as { limit: number }).limit).toBe(rig.core.cfg.dashboard.pageDefault);

      const huge = await apiGet(rig, steward, "/v1/dashboard/audit?limit=99999");
      expect((huge.json.page as { limit: number }).limit).toBe(rig.core.cfg.dashboard.pageMax);
      expect((huge.json.rows as unknown[]).length).toBeLessThanOrEqual(rig.core.cfg.dashboard.pageMax);
    });

    it("rejects a nonsensical limit rather than reinterpreting it", async () => {
      for (const limit of ["0", "-1", "abc", "1.5"]) {
        const res = await apiGet(rig, steward, `/v1/dashboard/audit?limit=${limit}`);
        expect(res.status, limit).toBe(400);
        expect(res.json.error, limit).toBe("invalid_argument");
      }
    });

    it("walks a keyset cursor without repeating or skipping a row", async () => {
      const seen: string[] = [];
      let cursor: string | null = null;
      for (let guard = 0; guard < 20; guard += 1) {
        const url: string = `/v1/dashboard/audit?limit=2${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
        const res = await apiGet(rig, steward, url);
        expect(res.status).toBe(200);
        seen.push(...(res.json.rows as { audit_id: string }[]).map((r) => r.audit_id));
        cursor = (res.json.page as { next_cursor: string | null }).next_cursor;
        if (!cursor) break;
      }
      expect(cursor).toBeNull(); // terminates
      expect(new Set(seen).size).toBe(seen.length); // no repeats

      const all = await apiGet(rig, steward, "/v1/dashboard/audit?limit=200");
      const every = (all.json.rows as { audit_id: string }[]).map((r) => r.audit_id);
      expect(new Set(seen)).toEqual(new Set(every)); // no skips
    });

    it("refuses a cursor it did not issue", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/audit?cursor=%7Bnot-a-cursor");
      expect(res.status).toBe(400);
      expect(res.json.error).toBe("invalid_cursor");
    });
  });

  // -- (b) publish deliveries ------------------------------------------------

  describe("publish deliveries read (§5.2, U-9)", () => {
    it("DT-1: a reporter sees only deliveries published under their own identity", async () => {
      const res = await apiGet(rig, reporter, "/v1/dashboard/deliveries");
      expect(res.status).toBe(200);
      const rows = res.json.rows as { artifact_id: string; subject: string }[];
      expect(rows.map((r) => r.artifact_id)).toEqual(["ra-reporter-1"]);
      expect([...new Set(rows.map((r) => r.subject))]).toEqual([USERS.reporter.username]);
    });

    it("DT-1: a crafted subject is refused, and another's artifact id returns nothing", async () => {
      const crafted = await apiGet(
        rig,
        reporter,
        `/v1/dashboard/deliveries?subject=${encodeURIComponent(USERS.steward.username)}`,
      );
      expect(crafted.status).toBe(403);

      // Naming the artifact directly does not widen the scope: the row
      // is simply absent (M-4 — hidden and nonexistent look the same).
      const byId = await apiGet(rig, reporter, "/v1/dashboard/deliveries?artifact_id=ra-steward-1");
      expect(byId.status).toBe(200);
      expect(byId.json.rows).toHaveLength(0);
    });

    it("a steward reads every delivery", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/deliveries");
      const ids = (res.json.rows as { artifact_id: string }[]).map((r) => r.artifact_id);
      expect(ids).toEqual(expect.arrayContaining(["ra-reporter-1", "ra-steward-1"]));
    });

    it("reports the dangling state and per-revision definition hashes", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/deliveries");
      const rows = res.json.rows as {
        artifact_id: string;
        dangling: boolean;
        delivery: { revision: number };
        attestations: { revision: number; definition_hash: string }[];
      }[];

      const attested = rows.find((r) => r.artifact_id === "ra-reporter-1")!;
      expect(attested.dangling).toBe(false);
      expect(attested.delivery.revision).toBe(2);
      expect(attested.attestations.map((a) => a.revision)).toEqual([1, 2]);
      expect(attested.attestations.map((a) => a.definition_hash)).toEqual([
        "sha256:def-1",
        "sha256:def-2",
      ]);

      const dangling = rows.find((r) => r.artifact_id === "ra-steward-1")!;
      expect(dangling.dangling).toBe(true);
      expect(dangling.attestations).toHaveLength(0);
    });

    it("filters by window", async () => {
      const future = new Date(Date.now() + 3_600_000).toISOString();
      const res = await apiGet(rig, steward, `/v1/dashboard/deliveries?since=${encodeURIComponent(future)}`);
      expect(res.json.rows).toHaveLength(0);
    });
  });

  // -- (c) ledger triage -----------------------------------------------------

  describe("ledger triage read (§5.3, U-5)", () => {
    // Issue titles are the *normalized* fingerprint scope (§3.3:
    // lowercased, stopwords stripped, sorted), not the description — so
    // these fixtures are told apart by a single distinctive token each.
    beforeAll(async () => {
      const filed = await fetch(`${rig.base}/v1/dashboard/ledger/requests`, {
        method: "POST",
        headers: { cookie: reporter.cookie, "x-cl-csrf": reporter.csrf, "content-type": "application/json" },
        body: JSON.stringify({ description: "nothing documents how refunds are counted" }),
      });
      expect(filed.status).toBe(201);
      const gap = await fetch(`${rig.base}/v1/dashboard/ledger/gaps`, {
        method: "POST",
        headers: { cookie: steward.cookie, "x-cl-csrf": steward.csrf, "content-type": "application/json" },
        body: JSON.stringify({ description: "the legacy sessions doc is missing entirely" }),
      });
      expect(gap.status).toBe(201);
    });

    it("DT-1: a reporter reads the requests they filed, not the steward's", async () => {
      const res = await apiGet(rig, reporter, "/v1/dashboard/ledger");
      expect(res.status).toBe(200);
      const titles = (res.json.issues as { title: string }[]).map((i) => i.title);
      expect(titles.some((t) => t.includes("refunds"))).toBe(true);
      expect(titles.some((t) => t.includes("legacy"))).toBe(false);
      expect((res.json.scope as { role_scope: string }).role_scope).toBe("self");
    });

    it("DT-1: a crafted filed_by for another identity is refused server-side", async () => {
      const res = await apiGet(
        rig,
        reporter,
        `/v1/dashboard/ledger?filed_by=${encodeURIComponent(USERS.steward.username)}`,
      );
      expect(res.status).toBe(403);
      expect(res.json.error).toBe("forbidden");
    });

    it("a steward reads the whole queue", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/ledger?limit=200");
      const titles = (res.json.issues as { title: string }[]).map((i) => i.title);
      expect(titles.some((t) => t.includes("refunds"))).toBe(true);
      expect(titles.some((t) => t.includes("legacy"))).toBe(true);
    });

    it("LED-R7: subjects are counts, never identities", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/ledger?limit=200");
      const issues = res.json.issues as Record<string, unknown>[];
      expect(issues.length).toBeGreaterThan(0);
      for (const issue of issues) {
        expect(issue).not.toHaveProperty("subject");
        expect(issue).not.toHaveProperty("subjects");
        expect(typeof issue.distinct_subjects).toBe("number");
      }
      // No identity string leaks through the serialized queue at all.
      expect(JSON.stringify(issues)).not.toContain(USERS.reporter.username);
    });

    it("orders the queue by the (occurrences, distinct_subjects) signal", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/ledger?limit=200");
      const issues = res.json.issues as { occurrences: number; distinct_subjects: number }[];
      for (let i = 1; i < issues.length; i += 1) {
        const prev = issues[i - 1]!;
        const cur = issues[i]!;
        expect(
          prev.occurrences > cur.occurrences ||
            (prev.occurrences === cur.occurrences && prev.distinct_subjects >= cur.distinct_subjects),
        ).toBe(true);
      }
    });

    it("an issue the caller did not file is not readable by id", async () => {
      const queue = await apiGet(rig, steward, "/v1/dashboard/ledger?limit=200");
      const stewardIssue = (queue.json.issues as { issue_id: string; title: string }[]).find((i) =>
        i.title.includes("legacy"),
      )!;
      const res = await apiGet(rig, reporter, `/v1/dashboard/ledger/issues/${stewardIssue.issue_id}`);
      expect(res.status).toBe(404);
    });
  });
});
