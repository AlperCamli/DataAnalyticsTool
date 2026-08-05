/**
 * B-0 ledger triage writes: the two inlets, steward verdicts, and the
 * deliver-batch trigger (dashboard spec §5.3, fault-ledger §4/§8
 * amendment, MCP §6.10 amendment).
 *
 * DT-11 is the load-bearing test: a reporter's verdict is a 403, a
 * steward's verdict records identity and timestamp, and **approve makes
 * no git call and writes no KB content** — asserted against the KB's
 * actual refs and PR store, not against a reading of the code. UI-11's
 * whole point is that the queue must not become the skip-the-diff button
 * through the side door.
 */

import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  apiGet,
  apiPost,
  login,
  setupDashboardRig,
  type BrowserSession,
  type DashboardRig,
} from "./dashboard-helpers.js";
import { callTool, USERS } from "./mcp-helpers.js";
import { DESCRIPTION_MAX, PROPOSAL_MAX } from "../src/ledger.js";

/** Script, markdown, a quoted literal, an address, an id-shaped run and
 * bare numbers — one payload covering every class LED-R2 drops and
 * every metacharacter LED-R5 defuses. */
const NASTY_PROPOSAL =
  '<script>alert(1)</script> **bold** [link](http://evil.example) ' +
  'ping ops@example.com with token abc123456789 and the "swordfish" password 42';

async function fileRequest(
  rig: DashboardRig,
  session: BrowserSession,
  body: Record<string, unknown>,
): Promise<string> {
  const res = await apiPost(rig, session, "/v1/dashboard/ledger/requests", body);
  expect(res.status).toBe(201);
  return res.json.issue_id as string;
}

describe("ledger triage writes (§5.3) — inlets, verdicts, batches", () => {
  let rig: DashboardRig;
  let reporter: BrowserSession;
  let steward: BrowserSession;

  beforeAll(async () => {
    rig = await setupDashboardRig();
    reporter = await login(rig, "reporter");
    steward = await login(rig, "steward");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  // -- inlets ----------------------------------------------------------------

  describe("the two inlets (human_filed, enrichment_request)", () => {
    it("files a gap under the filer's server-derived identity (LED-R3)", async () => {
      const res = await apiPost(rig, reporter, "/v1/dashboard/ledger/gaps", {
        description: "the checkout funnel has no documented entity",
        // A client-supplied subject is not a field this server reads.
        subject: "somebody-else",
      });
      expect(res.status).toBe(201);
      expect(res.json).toHaveProperty("issue_id");
      expect(res.json).toHaveProperty("occurrences");
      expect(res.json).toHaveProperty("routed_to");

      const { rows } = await rig.core.pool.query<{ subject: string; kind: string }>(
        `SELECT subject, kind FROM ledger_events WHERE issue_id = $1`,
        [res.json.issue_id],
      );
      expect(rows[0]!.subject).toBe(USERS.reporter.username);
      expect(rows[0]!.kind).toBe("human_filed");
    });

    it("opens an enrichment request with an optional proposal", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "no doc explains the marketing attribution window",
        proposal: "attribution uses a last-touch window agreed with the growth team",
      });
      const { rows } = await rig.core.pool.query<{ kind: string; detail: Record<string, unknown> }>(
        `SELECT e.kind, e.detail FROM ledger_events e WHERE e.issue_id = $1`,
        [issueId],
      );
      expect(rows[0]!.kind).toBe("enrichment_request");
      expect(rows[0]!.detail.proposal).toContain("last-touch window");

      const { rows: issue } = await rig.core.pool.query<{ status: string; kind: string }>(
        `SELECT status, kind FROM ledger_issues WHERE issue_id = $1`,
        [issueId],
      );
      expect(issue[0]!.status).toBe("open");
      expect(issue[0]!.kind).toBe("enrichment_request");
    });

    it("requires a description — a proposal never substitutes for naming the gap", async () => {
      const res = await apiPost(rig, reporter, "/v1/dashboard/ledger/requests", {
        proposal: "here is some content, but I never said what is missing",
      });
      expect(res.status).toBe(400);
      expect(res.json.error).toBe("invalid_argument");
    });

    it("FL-11: two requests on one target dedup to one issue with occurrences=2", async () => {
      const first = await fileRequest(rig, reporter, {
        description: "document this table",
        object: "drill.shop.customers",
      });
      const second = await fileRequest(rig, steward, {
        description: "please document this table too",
        object: "drill.shop.customers",
      });
      expect(second).toBe(first);

      const { rows } = await rig.core.pool.query<{ occurrences: number; distinct_subjects: number }>(
        `SELECT occurrences, distinct_subjects FROM ledger_issues WHERE issue_id = $1`,
        [first],
      );
      expect(rows[0]!.occurrences).toBe(2);
      expect(rows[0]!.distinct_subjects).toBe(2);
    });
  });

  // -- LED-R2 scrub + bounds + LED-R5 render ---------------------------------

  describe("proposal scrub and bounds (LED-R2 at storage, LED-R5 at render)", () => {
    it("stores a hostile proposal scrubbed, and serves it inert", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "the payments doc omits chargeback handling",
        proposal: NASTY_PROPOSAL,
      });

      // LED-R2 at storage: value-shaped tokens never land in the row.
      const { rows } = await rig.core.pool.query<{ detail: { proposal: string } }>(
        `SELECT detail FROM ledger_events WHERE issue_id = $1`,
        [issueId],
      );
      const stored = rows[0]!.detail.proposal;
      expect(stored).not.toContain("ops@example.com");
      expect(stored).not.toContain("swordfish"); // quoted literal
      expect(stored).not.toContain("abc123456789"); // id-shaped digit run
      expect(stored).not.toContain("42");
      expect(stored.length).toBeLessThanOrEqual(PROPOSAL_MAX);

      // LED-R5 at render: markdown/HTML metacharacters are inert.
      const view = await apiGet(rig, reporter, `/v1/dashboard/ledger/issues/${issueId}`);
      expect(view.status).toBe(200);
      const served = (view.json.events as { detail: { proposal: string } }[])[0]!.detail.proposal;
      expect(served).not.toContain("<script");
      expect(served).not.toContain("**");
      expect(served).not.toContain("](");
      expect(served).toContain("&lt;script");
    });

    it("bounds an oversized proposal at the same limit as a description", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "the inventory doc is missing entirely",
        proposal: "overlong ".repeat(400), // ~3600 chars
      });
      const { rows } = await rig.core.pool.query<{ detail: { proposal: string } }>(
        `SELECT detail FROM ledger_events WHERE issue_id = $1`,
        [issueId],
      );
      expect(rows[0]!.detail.proposal.length).toBeLessThanOrEqual(PROPOSAL_MAX);
      // The amendment's "identical treatment to description" is not a
      // coincidence of two numbers that happen to match today.
      expect(PROPOSAL_MAX).toBe(DESCRIPTION_MAX);
    });

    it("MT-14: flag_gap carries the same proposal treatment from a session", async () => {
      const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
        kind: "enrichment_request",
        description: "sessions have no documented retention rule",
        proposal: NASTY_PROPOSAL,
        // LED-R3: a client-supplied subject is ignored in favour of the
        // server-resolved one.
        subject: "somebody-else",
      });
      expect(result.isError).toBe(false);
      // The response shape is unchanged by the amendment.
      expect(Object.keys(result.payload).sort()).toEqual(
        ["issue_id", "occurrences", "refs", "routed_to"].sort(),
      );

      const { rows } = await rig.core.pool.query<{
        subject: string;
        detail: { proposal: string };
        detector_class: number;
        kind: string;
      }>(
        `SELECT subject, detail, detector_class, kind FROM ledger_events WHERE issue_id = $1`,
        [result.payload.issue_id],
      );
      expect(rows[0]!.subject).toBe(USERS.reporter.username);
      expect(rows[0]!.kind).toBe("enrichment_request");
      // §4: a human submission, recorded class 3 as result_disputed is.
      expect(rows[0]!.detector_class).toBe(3);
      expect(rows[0]!.detail.proposal).not.toContain("ops@example.com");
      expect(rows[0]!.detail.proposal).not.toContain("swordfish");
      expect(rows[0]!.detail.proposal.length).toBeLessThanOrEqual(PROPOSAL_MAX);
    });
  });

  // -- DT-11: verdicts -------------------------------------------------------

  describe("DT-11: steward verdicts are ledger state only", () => {
    it("a reporter's verdict call is a 403", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "nobody has written down how trials convert",
      });
      const res = await apiPost(rig, reporter, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "approve",
      });
      expect(res.status).toBe(403);
      expect(res.json.error).toBe("forbidden");

      const { rows } = await rig.core.pool.query<{ status: string; verdict_by: string | null }>(
        `SELECT status, verdict_by FROM ledger_issues WHERE issue_id = $1`,
        [issueId],
      );
      expect(rows[0]!.status).toBe("open");
      expect(rows[0]!.verdict_by).toBeNull();
    });

    it("a steward's approve records identity and timestamp — and makes no git call", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "the churn definition is undocumented",
      });

      // Everything the product could use to touch the KB, before.
      const gitBefore = rig.gitFingerprint();
      const headBefore = rig.kb.headSha();

      const before = new Date();
      const res = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "approve",
      });
      expect(res.status).toBe(200);
      const after = new Date();

      const verdict = (res.json.issue as { status: string; verdict: { by: string; at: string } });
      expect(verdict.status).toBe("approved");
      expect(verdict.verdict.by).toBe(USERS.steward.username);
      const at = new Date(verdict.verdict.at);
      expect(at.getTime()).toBeGreaterThanOrEqual(before.getTime() - 1000);
      expect(at.getTime()).toBeLessThanOrEqual(after.getTime() + 1000);

      const { rows } = await rig.core.pool.query<{
        status: string;
        verdict_by: string;
        verdict_at: Date;
      }>(`SELECT status, verdict_by, verdict_at FROM ledger_issues WHERE issue_id = $1`, [issueId]);
      expect(rows[0]!.status).toBe("approved");
      expect(rows[0]!.verdict_by).toBe(USERS.steward.username);
      expect(rows[0]!.verdict_at).toBeInstanceOf(Date);

      // UI-11: approve means "worth drafting". No branch, no commit, no
      // PR, no change to the KB's HEAD — the certification act is still
      // a human merging a reviewed diff.
      expect(rig.gitFingerprint()).toBe(gitBefore);
      expect(rig.kb.headSha()).toBe(headBefore);
    });

    it("a reject records the reason, scrubbed, for the filer's reply path", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "someone should document the deprecated pricing tiers",
      });
      const noReason = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
      });
      expect(noReason.status).toBe(400);

      const res = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: 'superseded by the "2026 pricing" rewrite; ping ops@example.com',
      });
      expect(res.status).toBe(200);
      const issue = res.json.issue as { status: string; verdict: { reason: string } };
      expect(issue.status).toBe("rejected");
      // LED-R2 binds the reason too — it is shown to the filer.
      expect(issue.verdict.reason).not.toContain("2026 pricing");
      expect(issue.verdict.reason).not.toContain("ops@example.com");
      expect(issue.verdict.reason).toContain("superseded by the");
    });

    it("verdicts apply to knowledge requests only, and only once", async () => {
      const gapRes = await apiPost(rig, reporter, "/v1/dashboard/ledger/gaps", {
        description: "an ordinary filed gap, not a knowledge request",
      });
      const wrongKind = await apiPost(
        rig,
        steward,
        `/v1/dashboard/ledger/issues/${gapRes.json.issue_id as string}/verdict`,
        { verdict: "approve" },
      );
      expect(wrongKind.status).toBe(400);
      expect(wrongKind.json.error).toBe("wrong_kind");

      const issueId = await fileRequest(rig, reporter, {
        description: "the referral programme has no written rules",
      });
      expect(
        (await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" }))
          .status,
      ).toBe(200);
      const again = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "changed my mind",
      });
      expect(again.status).toBe(409);
      expect(again.json.error).toBe("wrong_state");
    });

    it("an unknown issue is a 404", async () => {
      const res = await apiPost(
        rig,
        steward,
        "/v1/dashboard/ledger/issues/00000000-0000-4000-8000-000000000000/verdict",
        { verdict: "approve" },
      );
      expect(res.status).toBe(404);
    });
  });

  // -- deliver batch ---------------------------------------------------------

  describe("the deliver-batch trigger (§8)", () => {
    it("is steward-gated, bounded, and stamps approved requests batched", async () => {
      const denied = await apiPost(rig, reporter, "/v1/dashboard/ledger/batches", {});
      expect(denied.status).toBe(403);

      // Three fresh approved requests, plus whatever earlier tests left.
      for (const description of [
        "warehouse loading windows are undocumented",
        "the supplier onboarding flow has no entity doc",
        "nobody wrote down the refund approval ladder",
      ]) {
        const issueId = await fileRequest(rig, reporter, { description });
        expect(
          (await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" }))
            .status,
        ).toBe(200);
      }

      const res = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", { max: 2 });
      expect(res.status).toBe(201);
      expect(res.json.count).toBe(2);
      const batchId = res.json.batch_id as string;
      expect(batchId).toMatch(/^batch-/);

      const issues = res.json.issues as { status: string; batch_id: string }[];
      expect(issues.every((i) => i.status === "batched")).toBe(true);
      expect(issues.every((i) => i.batch_id === batchId)).toBe(true);

      // A second cut takes the next approved items, never the batched ones.
      const second = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", { max: 10 });
      expect(second.status).toBe(201);
      const secondIds = (second.json.issues as { issue_id: string }[]).map((i) => i.issue_id);
      const firstIds = (res.json.issues as { issue_id: string }[]).map((i) => i.issue_id);
      expect(secondIds.filter((id) => firstIds.includes(id))).toHaveLength(0);

      // Nothing here reached a repository either.
      const gitBefore = rig.gitFingerprint();
      await apiPost(rig, steward, "/v1/dashboard/ledger/batches", { max: 10 });
      expect(rig.gitFingerprint()).toBe(gitBefore);
    });

    it("caps a batch at the configured maximum", async () => {
      const res = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", { max: 9999 });
      expect(res.status).toBe(201);
      expect((res.json.count as number)).toBeLessThanOrEqual(rig.core.cfg.dashboard.batchMax);
    });
  });
});
