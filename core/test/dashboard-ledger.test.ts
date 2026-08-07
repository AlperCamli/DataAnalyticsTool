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

  describe("authored text is kept and flagged; derived text is still scrubbed (D-115)", () => {
    it("stores an authored proposal verbatim, flags what it contains, and still serves it inert", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "the payments doc omits chargeback handling",
        proposal: NASTY_PROPOSAL,
      });

      // D-115 at storage: the person's words are kept, all of them. The
      // ruling that changed this was bought by B1-F6 — a reporter's
      // subscription prices deleted at storage, the steward approving a
      // sentence with its payload gone, and nobody told at any point.
      const { rows } = await rig.core.pool.query<{
        detail: { proposal: string };
        value_flags: string[];
      }>(`SELECT detail, value_flags FROM ledger_events WHERE issue_id = $1`, [issueId]);
      const stored = rows[0]!.detail.proposal;
      expect(stored).toBe(NASTY_PROPOSAL);
      expect(stored).toContain("ops@example.com");
      expect(stored).toContain("swordfish");
      expect(stored).toContain("abc123456789");
      expect(stored).toContain("42");

      // ...and the patterns that used to delete now report. This is the
      // whole of the exchange: a warning two humans can act on, in place
      // of an edit neither of them could see.
      expect([...rows[0]!.value_flags].sort()).toEqual(
        ["digit_run", "email", "number", "quoted"].sort(),
      );

      // LED-R5 at render is UNCHANGED and matters more now, not less:
      // verbatim storage means the render boundary is the only thing
      // between a hostile submission and a steward's browser.
      const view = await apiGet(rig, reporter, `/v1/dashboard/ledger/issues/${issueId}`);
      expect(view.status).toBe(200);
      const event = (view.json.events as { detail: { proposal: string }; value_flags: string[] }[])[0]!;
      expect(event.detail.proposal).not.toContain("<script");
      expect(event.detail.proposal).not.toContain("**");
      expect(event.detail.proposal).not.toContain("](");
      expect(event.detail.proposal).toContain("&lt;script");
      // The filer's own copy of the warning rides the event.
      expect(event.value_flags).toContain("email");

      // And the steward reads it on the issue itself, without opening
      // the stream — the union across every filing on that issue.
      const list = await apiGet(rig, steward, `/v1/dashboard/ledger?status=all&limit=100`);
      const issue = (list.json.issues as { issue_id: string; value_flags: string[] }[]).find(
        (i) => i.issue_id === issueId,
      )!;
      expect(issue.value_flags).toContain("email");
    });

    it("tells the filer what their submission contains, at the moment they file it", async () => {
      // The half B1-F6 was actually about. The old rule edited silently;
      // a filer who is not told cannot re-send what was removed.
      const res = await apiPost(rig, reporter, "/v1/dashboard/ledger/requests", {
        description: "weekly subscription is 4.99 dollars, monthly 14.99",
      });
      expect(res.status).toBe(201);
      expect(res.json.value_flags).toContain("number");

      const { rows } = await rig.core.pool.query<{ description: string }>(
        `SELECT description FROM ledger_events WHERE issue_id = $1`,
        [res.json.issue_id],
      );
      // The pilot's own sentence, and the exact thing that was lost.
      expect(rows[0]!.description).toContain("4.99");
      expect(rows[0]!.description).toContain("14.99");
    });

    it("a derived kind is still scrubbed — LED-R2's threat model is untouched", async () => {
      // class 2: the *agent* wrote this description from a session, which
      // is the case D-66.5 was written for. The line is provenance, not
      // detector class or field name.
      const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
        kind: "missing_doc",
        description: "no doc for the ledger table holding balance 4321.55 for ops@example.com",
        object: "supabase.public.orders",
      });
      expect(result.isError).toBe(false);
      const { rows } = await rig.core.pool.query<{ description: string; value_flags: string[] }>(
        `SELECT description, value_flags FROM ledger_events WHERE issue_id = $1`,
        [result.payload.issue_id],
      );
      expect(rows[0]!.description).not.toContain("4321.55");
      expect(rows[0]!.description).not.toContain("ops@example.com");
      // Nothing to warn about: the values are gone, as they always were.
      expect(rows[0]!.value_flags).toEqual([]);
    });

    it("bounds an oversized proposal at 2000 and says that it did", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "the inventory doc is missing entirely",
        proposal: "overlong ".repeat(400), // ~3600 chars
      });
      const { rows } = await rig.core.pool.query<{
        detail: { proposal: string };
        value_flags: string[];
      }>(`SELECT detail, value_flags FROM ledger_events WHERE issue_id = $1`, [issueId]);
      expect(rows[0]!.detail.proposal.length).toBeLessThanOrEqual(PROPOSAL_MAX);
      // D-115: a bound that bites silently is the same defect the ruling
      // removed, so truncation reports itself like everything else.
      expect(rows[0]!.value_flags).toContain("truncated");
      // D-106.4: the alias is gone by intent. Suggested content carries
      // enum decodings and structure sketches; a description does not.
      expect(PROPOSAL_MAX).toBe(2000);
      expect(DESCRIPTION_MAX).toBe(500);
    });

    it("keeps an enum decoding intact — the content the wide bound was for", async () => {
      // Under D-106.4 this survived the *length* bound and was then
      // gutted by the scrub: `0 = pending` became `= pending`, which is
      // the exact contradiction D-115 resolves.
      const enumSketch = Array.from(
        { length: 40 },
        (_, i) => `status_${String.fromCharCode(97 + (i % 26))}${i} means the order is in stage ${i}`,
      ).join("; ");
      expect(enumSketch.length).toBeGreaterThan(DESCRIPTION_MAX * 3);
      expect(enumSketch.length).toBeLessThan(PROPOSAL_MAX);
      const issueId = await fileRequest(rig, reporter, {
        description: "the order status enum is undocumented",
        proposal: enumSketch,
      });
      const { rows } = await rig.core.pool.query<{ detail: { proposal: string } }>(
        `SELECT detail FROM ledger_events WHERE issue_id = $1`,
        [issueId],
      );
      const stored = rows[0]!.detail.proposal;
      expect(stored).toBe(enumSketch);
      // The stage numbers ARE the decoding. Before D-115 this assertion
      // was inverted, and that inversion is what made the field useless.
      expect(/stage \d/.test(stored)).toBe(true);
      expect(stored).toContain("stage 39");
    });

    it("MT-14: flag_gap carries the same treatment, and relays the warning to the agent", async () => {
      const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
        kind: "enrichment_request",
        description: "sessions have no documented retention rule",
        proposal: NASTY_PROPOSAL,
        // LED-R3: a client-supplied subject is ignored in favour of the
        // server-resolved one.
        subject: "somebody-else",
      });
      expect(result.isError).toBe(false);
      // D-115 widens the response: the agent is told what the user's
      // submission contains so it can say so out loud, which is the
      // session-side half of the same warning the form renders.
      expect(Object.keys(result.payload).sort()).toEqual(
        ["issue_id", "occurrences", "refs", "routed_to", "value_flags", "value_flags_note"].sort(),
      );
      expect(result.payload.value_flags).toContain("email");

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
      expect(rows[0]!.detail.proposal).toBe(NASTY_PROPOSAL);
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

    it("D-106.5: a rejected request refiled reopens with its verdict preserved", async () => {
      const object = "drill.shop.refund_ledger";
      const issueId = await fileRequest(rig, reporter, {
        description: "no document explains how refunds are counted",
        object,
      });
      const rejected = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "the finance wiki covers this; not KB material",
      });
      expect(rejected.status).toBe(200);

      // A second person hits the same wall. Same fingerprint (§3.3), so
      // the same issue — symmetric with L-4's wont_fix rule.
      const other = await login(rig, "restricted");
      const refiled = await apiPost(rig, other, "/v1/dashboard/ledger/requests", {
        description: "refund counting is still undocumented",
        object,
      });
      expect(refiled.status).toBe(201);
      expect(refiled.json.issue_id).toBe(issueId);
      expect(refiled.json.occurrences).toBe(2);

      const view = await apiGet(rig, steward, `/v1/dashboard/ledger/issues/${issueId}`);
      const issue = view.json.issue as {
        status: string;
        occurrences: number;
        distinct_subjects: number;
        reopen_count: number;
        verdict: { by: string; reason: string } | null;
      };
      // Reopened, cumulative, and the prior verdict still legible: the
      // steward reads "rejected before, refiled by N more".
      expect(issue.status).toBe("open");
      expect(issue.occurrences).toBe(2);
      expect(issue.distinct_subjects).toBe(2);
      expect(issue.reopen_count).toBe(1);
      expect(issue.verdict?.by).toBe(USERS.steward.username);
      expect(issue.verdict?.reason).toContain("finance wiki");

      // …and may re-reject, because the issue is open again.
      const again = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "still not KB material",
      });
      expect(again.status).toBe(200);
      expect((again.json.issue as { status: string }).status).toBe("rejected");
      expect((again.json.issue as { reopen_count: number }).reopen_count).toBe(1);
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

  // -- MT-15: the batch is readable over the channel a session has ----------
  //
  // Finding B1-F8. S1b told the session to read its batch from
  // `/v1/dashboard/ledger` with a bearer token; a compiled bundle carries
  // no credential (PA-1) and the MCP client's token is not reachable from
  // the session's shell, so the instruction named a token that cannot
  // exist. The fix is the tool the session already holds (D-116.5), so
  // the test is: file → approve → deliver → read it back with `list_gaps`,
  // and get everything a citation needs.

  describe("MT-15: list_gaps reads the delivered batch (§6.11.1, D-116.5)", () => {
    it("returns the filing verbatim, inert, with the identity the server recorded", async () => {
      const proposal =
        'A refund is counted in the month the credit note is issued, not the order month. ' +
        NASTY_PROPOSAL;
      const issueId = await fileRequest(rig, reporter, {
        description: "nothing says which month a refund lands in",
        proposal,
      });
      expect(
        (await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" }))
          .status,
      ).toBe(200);
      const batch = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", { max: 10 });
      expect(batch.status).toBe(201);

      const listed = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {
        status: "batched",
        kind: "enrichment_request",
        limit: 50,
      });
      expect(listed.isError).toBe(false);
      const issues = listed.payload.issues as {
        issue_id: string;
        status: string;
        filing: { by: string; at: string; description: string; proposal?: string; value_flags: string[] };
      }[];
      const mine = issues.find((i) => i.issue_id === issueId);
      expect(mine, "the batched request is readable over MCP").toBeTruthy();
      expect(mine!.status).toBe("batched");

      // What citation needs: whose words, and when — from the ledger, not
      // from the body of the request (LED-R3).
      expect(mine!.filing.by).toBe(USERS.reporter.username);
      expect(mine!.filing.at).toMatch(/^\d{4}-\d{2}-\d{2}T/);

      // The words themselves: nothing deleted (D-115 — an authored
      // proposal is flagged, never edited). The email and the number are
      // still there; LED-R5 has defused the metacharacters around them,
      // which is a different operation from removing content and this
      // pair of assertions is what tells them apart.
      expect(mine!.filing.proposal).toContain("credit note is issued");
      expect(mine!.filing.proposal).toContain("42");
      expect(mine!.filing.proposal).toContain("ops&#64;example.com");
      expect(mine!.filing.proposal).not.toContain("<script>");
      expect(mine!.filing.description).not.toContain("<script>");
      // The stored row is the un-neutralized original — the escaping is a
      // property of this render point, not of the ledger.
      const { rows: stored } = await rig.core.pool.query<{ detail: { proposal: string } }>(
        `SELECT detail FROM ledger_events WHERE issue_id = $1`,
        [issueId],
      );
      expect(stored[0]!.detail.proposal).toBe(proposal);

      // … and the warning travels with the words.
      expect(mine!.filing.value_flags).toContain("email");
      expect(mine!.filing.value_flags).toContain("number");
    });

    it("a reporter's call is still permission_denied, and returns no issue", async () => {
      const denied = await callTool(rig, rig.token("reporter"), "reporter", "list_gaps", {
        status: "batched",
      });
      expect(denied.isError).toBe(true);
      expect(denied.payload.code).toBe("permission_denied");
      expect(denied.payload).not.toHaveProperty("issues");
    });

    it("`rejected` is refused rather than silently read as the open queue", async () => {
      const bad = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {
        status: "rejected",
      });
      expect(bad.isError).toBe(true);
      expect(bad.payload.code).toBe("invalid_argument");
      expect(String(bad.payload.message)).toContain("not work");
    });

    it("`approved` reads the worklist a batch has not yet claimed", async () => {
      const issueId = await fileRequest(rig, reporter, {
        description: "the dunning schedule is written down nowhere",
      });
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" });
      const listed = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {
        status: "approved",
        kind: "enrichment_request",
        limit: 50,
      });
      const ids = (listed.payload.issues as { issue_id: string }[]).map((i) => i.issue_id);
      expect(ids).toContain(issueId);
    });
  });

  // -- MT-16: the write half of the same surface -----------------------------
  //
  // Finding B1-F9, authorized as D-118.3. MT-15 made the batch readable
  // by the session that must act on it; the third per-item outcome —
  // hand it back — remained a governed write with no session-reachable
  // inlet, so the skill could say "handed back" and never move the row.
  // The test walks the whole way round: file → approve → deliver →
  // return over MCP → the row is `approved` again, the note is on it,
  // an audit row exists, and the next `list_gaps(status: "batched")`
  // no longer offers it as work.

  describe("MT-16: return_request hands a batched request back (§6.12, D-118.3)", () => {
    async function batchedIssue(description: string): Promise<string> {
      const issueId = await fileRequest(rig, reporter, { description });
      expect(
        (await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" }))
          .status,
      ).toBe(200);
      expect((await apiPost(rig, steward, "/v1/dashboard/ledger/batches", { max: 10 })).status).toBe(201);
      return issueId;
    }

    it("moves batched → approved with the note, and audits the call", async () => {
      const issueId = await batchedIssue("no doc says what a dormant account is");
      const note = "belongs on the accounts doc, which is contaminated; waiting for it to be repaired to draft";

      const gitBefore = rig.gitFingerprint();
      const res = await callTool(rig, rig.token("steward"), "steward", "return_request", {
        issue_id: issueId,
        note,
      });
      expect(res.isError).toBe(false);
      expect(res.payload.issue_id).toBe(issueId);
      expect(res.payload.status).toBe("approved");
      expect(String(res.payload.note)).toContain("waiting for it to be repaired");

      // The row moved, and the note is on it where the next steward reads it.
      const { rows } = await rig.core.pool.query<{
        status: string;
        batch_id: string | null;
        return_note: string | null;
        returned_at: string | null;
      }>(`SELECT status, batch_id, return_note, returned_at FROM ledger_issues WHERE issue_id = $1`, [issueId]);
      expect(rows[0]!.status).toBe("approved");
      expect(rows[0]!.batch_id).toBeNull();
      expect(rows[0]!.return_note).toContain("contaminated");
      expect(rows[0]!.returned_at).toBeTruthy();

      // It is a ledger-state write and nothing else: no git call, and the
      // request stays open, which is the truth — nobody answered it.
      expect(rig.gitFingerprint()).toBe(gitBefore);

      // The batch no longer offers it as work.
      const listed = await callTool(rig, rig.token("steward"), "steward", "list_gaps", {
        status: "batched",
        kind: "enrichment_request",
        limit: 50,
      });
      const batchedIds = (listed.payload.issues as { issue_id: string }[]).map((i) => i.issue_id);
      expect(batchedIds).not.toContain(issueId);

      // M-8: the governed write is in the audit under the caller's own
      // identity, with the issue in result_meta and no note text.
      const { rows: audit } = await rig.core.pool.query<{
        subject: string;
        decision: string;
        result_meta: Record<string, unknown>;
      }>(
        `SELECT subject, decision, result_meta FROM audit_records
          WHERE tool = 'return_request' ORDER BY ts DESC LIMIT 1`,
      );
      expect(audit[0]!.subject).toBe(USERS.steward.username);
      expect(audit[0]!.decision).toBe("allowed");
      expect(audit[0]!.result_meta.issue_id).toBe(issueId);
      expect(JSON.stringify(audit[0]!.result_meta)).not.toContain("contaminated");
    });

    it("a reporter's call is permission_denied and moves nothing", async () => {
      const issueId = await batchedIssue("nobody has written down what a trial is");
      const denied = await callTool(rig, rig.token("reporter"), "reporter", "return_request", {
        issue_id: issueId,
        note: "I would like this back please",
      });
      expect(denied.isError).toBe(true);
      expect(denied.payload.code).toBe("permission_denied");

      const { rows } = await rig.core.pool.query<{ status: string }>(
        `SELECT status FROM ledger_issues WHERE issue_id = $1`,
        [issueId],
      );
      expect(rows[0]!.status).toBe("batched");

      // The refusal is in the audit too — a denied governed write is
      // exactly the row an investigator wants.
      const { rows: audit } = await rig.core.pool.query<{ decision: string }>(
        `SELECT decision FROM audit_records WHERE tool = 'return_request' AND subject = $1
          ORDER BY ts DESC LIMIT 1`,
        [USERS.reporter.username],
      );
      expect(audit[0]!.decision).toBe("denied");
    });

    it("refuses a return with no note — the state change without the reason", async () => {
      const issueId = await batchedIssue("the invoice numbering scheme is undocumented");
      const bad = await callTool(rig, rig.token("steward"), "steward", "return_request", {
        issue_id: issueId,
        note: "   ",
      });
      expect(bad.isError).toBe(true);
      expect(bad.payload.code).toBe("invalid_argument");
      expect(String(bad.payload.message)).toContain("what evidence would unblock");

      const { rows } = await rig.core.pool.query<{ status: string }>(
        `SELECT status FROM ledger_issues WHERE issue_id = $1`,
        [issueId],
      );
      expect(rows[0]!.status).toBe("batched");
    });

    it("a second return is refused, naming the state it is actually in", async () => {
      const issueId = await batchedIssue("what counts as an active seat is not written down");
      const first = await callTool(rig, rig.token("steward"), "steward", "return_request", {
        issue_id: issueId,
        note: "needs the finance team to say which seats they count",
      });
      expect(first.isError).toBe(false);

      const second = await callTool(rig, rig.token("steward"), "steward", "return_request", {
        issue_id: issueId,
        note: "needs the finance team to say which seats they count",
      });
      expect(second.isError).toBe(true);
      expect(second.payload.code).toBe("invalid_argument");
      expect(String(second.payload.message)).toContain("approved");
      expect(String(second.payload.message)).toContain("only a batched request can be returned");
    });

    it("an unknown issue is not_found, and a note that lost content says so", async () => {
      const missing = await callTool(rig, rig.token("steward"), "steward", "return_request", {
        issue_id: "00000000-0000-4000-8000-000000000000",
        note: "nothing to return",
      });
      expect(missing.isError).toBe(true);
      expect(missing.payload.code).toBe("not_found");

      // D-115's rule on the one text this tool writes: the note is
      // scrubbed at storage exactly as a rejection reason is, and the
      // caller is shown what was actually recorded rather than left to
      // assume their words survived.
      const issueId = await batchedIssue("nobody documented the renewal window");
      const res = await callTool(rig, rig.token("steward"), "steward", "return_request", {
        issue_id: issueId,
        note: 'needs the "renewal window" length in days, currently guessed at 30',
      });
      expect(res.isError).toBe(false);
      expect(res.payload.note_altered).toBe(true);
      expect(String(res.payload.note)).not.toContain("30");
      expect(String(res.payload.note_altered_note)).toContain("what the steward and the filer will read");
    });
  });
});
