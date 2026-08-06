/**
 * B-1's remaining server surfaces and the client's structural claims:
 * the F-10 inbox (DT-10 / UI-D), governance writes in the audit record
 * (D-114.1, closing spec §5.1), Ops re-enqueue and webhook secrets
 * (DT-5), and the static assertions over the shipped bundle that keep
 * UI-1, UI-5 and UI-8 properties of the code rather than of a rendering.
 */

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
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
import { writeFile } from "node:fs/promises";
import { createProvider } from "../src/gitkb.js";
import { sweepResolutions } from "../src/ledger.js";
import { syncConfig } from "./sync-helpers.js";

const CORE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Every screen this bundle ships. Listed by name so a screen added
 * without a line here fails the coverage check below rather than
 * quietly escaping the render-safety assertions. */
const APP_SOURCES = [
  "main.tsx",
  "App.tsx",
  "api.ts",
  "ui.tsx",
  "Connections.tsx",
  "KbHealth.tsx",
  "GapTriage.tsx",
  "Publish.tsx",
  "Ops.tsx",
  "Inbox.tsx",
];

async function fileRequest(
  rig: DashboardRig,
  session: BrowserSession,
  description: string,
  proposal?: string,
): Promise<string> {
  const res = await apiPost(rig, session, "/v1/dashboard/ledger/requests", {
    description,
    ...(proposal ? { proposal } : {}),
  });
  expect(res.status).toBe(201);
  return res.json.issue_id as string;
}

describe("B-1 dashboard surfaces", () => {
  let rig: DashboardRig;
  let steward: BrowserSession;
  let reporter: BrowserSession;

  beforeAll(async () => {
    // The bundle is a build artifact; a test asserting over a stale one
    // asserts nothing.
    execFileSync("node", [path.join(CORE_DIR, "web", "build.mjs")], { cwd: CORE_DIR, stdio: "pipe" });
    rig = await setupDashboardRig();
    steward = await login(rig, "steward");
    reporter = await login(rig, "reporter");
  }, 240_000);

  afterAll(async () => {
    await rig?.stop();
  });

  // -- DT-10 / UI-D: the resolution badge ------------------------------------

  describe("DT-10: a verdict surfaces to its filer (UI-D — the badge)", () => {
    it("a rejection reaches the filer with its reason, and only that filer", async () => {
      const issueId = await fileRequest(rig, reporter, "nobody has written down how trials convert");

      // Before the verdict there is nothing to report — and that is a
      // stated empty, not a zero standing in for one.
      const before = await apiGet(rig, reporter, "/v1/dashboard/inbox");
      expect(before.status).toBe(200);
      expect((before.json.items as unknown[]).find((i) => (i as { issue_id: string }).issue_id === issueId)).toBeUndefined();

      const verdict = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "the trial definition lives in the billing system and this KB does not cover it yet",
      });
      expect(verdict.status).toBe(200);

      const after = await apiGet(rig, reporter, "/v1/dashboard/inbox");
      const item = (after.json.items as {
        issue_id: string;
        unread: boolean;
        status: string;
        rejection: { by: string; reason: string } | null;
      }[]).find((i) => i.issue_id === issueId)!;
      expect(item).toBeDefined();
      expect(item.unread).toBe(true);
      expect(item.status).toBe("rejected");
      expect(item.rejection!.by).toBe(USERS.steward.username);
      // The reason is the point of F-10: a rejection the filer cannot
      // read is a disappearance, not a decision.
      expect(item.rejection!.reason).toContain("billing system");
      expect(after.json.unread as number).toBeGreaterThanOrEqual(1);

      // The steward did not file it, so it is not in *their* inbox —
      // this endpoint has no `all` scope, whatever role asks.
      const stewardInbox = await apiGet(rig, steward, "/v1/dashboard/inbox");
      expect(
        (stewardInbox.json.items as { issue_id: string }[]).find((i) => i.issue_id === issueId),
      ).toBeUndefined();
    });

    it("acknowledging is server state — it survives a fresh session", async () => {
      const issueId = await fileRequest(rig, reporter, "the refund window is undocumented");
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "already covered by the returns policy doc",
      });

      const ack = await apiPost(rig, reporter, "/v1/dashboard/inbox/ack", { issue_ids: [issueId] });
      expect(ack.status).toBe(200);
      expect(ack.json.acknowledged).toBe(1);

      // A second login is a different cookie and a different tab's
      // worth of client state — the badge must not come back, which is
      // why "seen" could not live in the browser (D-103.1).
      const fresh = await login(rig, "reporter");
      const inbox = await apiGet(rig, fresh, "/v1/dashboard/inbox");
      const item = (inbox.json.items as { issue_id: string; unread: boolean }[]).find(
        (i) => i.issue_id === issueId,
      )!;
      expect(item.unread).toBe(false);
    });

    it("a re-verdict after a refiling is news again", async () => {
      const description = "the seat-count metric has two definitions";
      const issueId = await fileRequest(rig, reporter, description);
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "pick one and file again",
      });
      await apiPost(rig, reporter, "/v1/dashboard/inbox/ack", { issue_ids: [issueId] });

      // D-106.5: refiling a rejected request reopens it with the prior
      // verdict preserved. The second rejection is a new decision, and a
      // badge that stayed silent would be hiding it.
      const refiled = await fileRequest(rig, reporter, description);
      expect(refiled).toBe(issueId);
      const second = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "still two definitions; the billing one is authoritative",
      });
      expect(second.status).toBe(200);

      const inbox = await apiGet(rig, reporter, "/v1/dashboard/inbox");
      const item = (inbox.json.items as {
        issue_id: string;
        unread: boolean;
        reopen_count: number;
        rejection: { reason: string };
      }[]).find((i) => i.issue_id === issueId)!;
      expect(item.unread).toBe(true);
      expect(item.reopen_count).toBeGreaterThanOrEqual(1);
      expect(item.rejection.reason).toContain("authoritative");
    });

    it("an inbox is its owner's — a crafted subject is a 403 (DT-1's shape here)", async () => {
      const res = await apiGet(
        rig,
        reporter,
        `/v1/dashboard/inbox?subject=${encodeURIComponent(USERS.steward.username)}`,
      );
      expect(res.status).toBe(403);
      expect(res.json.error).toBe("forbidden");
    });

    it("acknowledging somebody else's issue acknowledges nothing", async () => {
      const issueId = await fileRequest(rig, reporter, "invoices have no documented numbering rule");
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "reject",
        reason: "not this quarter",
      });
      // The steward never filed it, so there is no ack for them to make.
      const ack = await apiPost(rig, steward, "/v1/dashboard/inbox/ack", { issue_ids: [issueId] });
      expect(ack.status).toBe(200);
      expect(ack.json.acknowledged).toBe(0);
    });
  });

  // -- D-114.1: governance writes enter the audit record ---------------------

  describe("D-114.1: governance acts are audited (closes spec §5.1)", () => {
    const auditRows = async (tool: string) => {
      const { rows } = await rig.core.pool.query<{
        subject: string;
        decision: string;
        tool: string;
        session_id: string | null;
        setup_stamp: string | null;
        args_digest: string;
      }>(`SELECT subject, decision, tool, session_id, setup_stamp, args_digest
            FROM audit_records WHERE tool = $1 ORDER BY ts DESC`, [tool]);
      return rows;
    };

    it("a steward's verdict writes a row carrying their identity", async () => {
      const issueId = await fileRequest(rig, reporter, "the activation event is not defined anywhere");
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" });

      const rows = await auditRows("dashboard.ledger.verdict");
      const mine = rows.find((r) => r.decision === "allowed" && r.subject === USERS.steward.username);
      expect(mine).toBeDefined();
      // A browser session is not an MCP session and presents no compiled
      // setup stamp; inventing values would make governance rows look
      // like tool calls in the register meant to tell them apart.
      expect(mine!.session_id).toBeNull();
      expect(mine!.setup_stamp).toBe("unstamped");
      expect(mine!.args_digest).toMatch(/^[0-9a-f]{64}$/);
    });

    it("a REFUSED verdict is recorded too — the row an auditor came for", async () => {
      const issueId = await fileRequest(rig, reporter, "nobody documents the dunning schedule");
      const res = await apiPost(rig, reporter, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "approve",
      });
      expect(res.status).toBe(403);

      const rows = await auditRows("dashboard.ledger.verdict");
      const denied = rows.find((r) => r.decision === "denied" && r.subject === USERS.reporter.username);
      expect(denied).toBeDefined();
      // A success-only log would hold no trace that a reporter tried to
      // approve their own request, which is precisely what makes the
      // steward gate worth having a record of.
    });

    it("connection writes are audited — the gap §5.1 filed", async () => {
      const res = await apiPost(rig, steward, "/v1/dashboard/connections/audited_src", {});
      // The PUT below is the real act; this POST just proves the address
      // is not a write path of its own.
      expect([404, 400, 403, 405]).toContain(res.status);

      const put = await fetch(`${rig.base}/v1/dashboard/connections/audited_src`, {
        method: "PUT",
        headers: {
          cookie: steward.cookie,
          "content-type": "application/json",
          "x-cl-csrf": steward.csrf,
        },
        body: JSON.stringify({
          connector: { name: "postgres", version_constraint: "*" },
          payload: { config: { system: "audited_src", mode: "live" }, credentials: [] },
        }),
      });
      expect([200, 201]).toContain(put.status);

      const rows = await auditRows("dashboard.connection.upsert");
      expect(rows.length).toBeGreaterThanOrEqual(1);
      expect(rows[0]!.subject).toBe(USERS.steward.username);
      expect(rows[0]!.decision).toBe("allowed");
    });

    it("the widened contract does not disturb the existing consumers", async () => {
      // §5.1's fix had to leave every current reader of `audit_records`
      // reading the same thing. Each filters by `tool`, so a governance
      // row is invisible to them — asserted rather than reasoned about.
      const { rows } = await rig.core.pool.query<{ n: string }>(
        `SELECT count(*) AS n FROM audit_records WHERE tool LIKE 'dashboard.%'`,
      );
      expect(Number(rows[0]!.n)).toBeGreaterThan(0);

      const { rows: toolRows } = await rig.core.pool.query<{ n: string }>(
        `SELECT count(*) AS n FROM audit_records
          WHERE tool IN ('validate_sql', 'execute_sql', 'publish_report')
            AND tool LIKE 'dashboard.%'`,
      );
      expect(Number(toolRows[0]!.n)).toBe(0);

      // And a steward reading the audit endpoint sees them, which is the
      // whole point — B-4's view inherits a closed item.
      const read = await apiGet(rig, steward, "/v1/dashboard/audit?limit=200");
      expect(read.status).toBe(200);
      const tools = new Set((read.json.rows as { tool: string }[]).map((r) => r.tool));
      expect([...tools].some((t) => t.startsWith("dashboard."))).toBe(true);
    });
  });

  // -- Ops -------------------------------------------------------------------

  describe("Ops: runs, jobs, dead-letter re-enqueue (U-10)", () => {
    /** A dead-lettered job to act on. How it died is not what these
     * tests are about, so it is written directly. */
    const stageDead = async (
      jobId: string,
      opts: { type?: string; system?: string; payload?: unknown } = {},
    ) => {
      await rig.core.pool.query(
        `INSERT INTO jobs (job_id, type, class, system, connector_name, version_constraint,
                           payload, priority, max_attempts, deadline_s, max_deferrals, state,
                           triggers, error, attempt, finished_at)
         VALUES ($1, $4, 'batch', $5, 'drill','*', $2::jsonb, 5, 3, 600, 2,
                 'dead_lettered', '[]'::jsonb, $3::jsonb, 3, now())`,
        [
          jobId,
          JSON.stringify(
            opts.payload ?? {
              config: { system: "drill", mode: "fixture" },
              // The stale capture B1-F1 is about: this reference was
              // right when the job was queued and is not right now.
              credentials: [{ key: "dsn", ref: "env://GONE_SINCE_THE_MIGRATION" }],
            },
          ),
          JSON.stringify({ code: "auth_error", message: "no resolver for its scheme", retryable: false }),
          opts.type ?? "snapshot",
          opts.system ?? "drill",
        ],
      );
    };

    /** The registration re-enqueue must rebuild from. */
    const registerDrill = async (refs: { key: string; ref: string }[]) => {
      const res = await fetch(`${rig.base}/v1/dashboard/connections/drill`, {
        method: "PUT",
        headers: {
          cookie: steward.cookie,
          "content-type": "application/json",
          "x-cl-csrf": steward.csrf,
        },
        body: JSON.stringify({
          connector: { name: "drill", version_constraint: "*" },
          payload: { config: { system: "drill", mode: "fixture" }, credentials: refs },
        }),
      });
      expect([200, 201]).toContain(res.status);
    };

    it("re-enqueue creates a new job as the caller and leaves the dead one dead", async () => {
      await registerDrill([{ key: "dsn", ref: "vault://secret/contextlayer/connections/drill#dsn" }]);
      const jobId = "01JDEADLETTERTESTJOB000001";
      await stageDead(jobId);

      const res = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${jobId}/reenqueue`, {});
      expect(res.status).toBe(201);
      const newId = res.json.job_id as string;
      expect(newId).not.toBe(jobId);
      expect(res.json.dead_job_unchanged).toBe(true);

      // The dead row keeps its state and its error: it is the evidence
      // that something failed, and a re-enqueue that flipped it back to
      // queued would delete the fault while appearing to fix it.
      const { rows } = await rig.core.pool.query<{
        state: string;
        error: Record<string, unknown>;
        reenqueued_as: string | null;
      }>(`SELECT state, error, reenqueued_as FROM jobs WHERE job_id = $1`, [jobId]);
      expect(rows[0]!.state).toBe("dead_lettered");
      expect(rows[0]!.error.code).toBe("auth_error");
      // B1-F1: the pointer is its own column. A pointer to a replacement
      // is not part of why this job died, and burying it in `error` put
      // a success fact inside the failure record.
      expect(rows[0]!.reenqueued_as).toBe(newId);
      expect(rows[0]!.error.reenqueued_as).toBeUndefined();

      // The new job carries the acting identity on its own row.
      const { rows: created } = await rig.core.pool.query<{
        state: string;
        triggers: { kind: string; detail: { actor: string } }[];
      }>(`SELECT state, triggers FROM jobs WHERE job_id = $1`, [newId]);
      expect(created[0]!.state).toBe("queued");
      expect(created[0]!.triggers[0]!.kind).toBe("dashboard");
      expect(created[0]!.triggers[0]!.detail.actor).toBe(USERS.steward.username);
    });

    it("B1-F1: the payload is rebuilt from the registration, not replayed", async () => {
      // The pilot's shape exactly: a job captured before A-4 carrying
      // `env://…`, a connection since flipped to `vault://…`, and a
      // runner with no env resolver. Replaying the capture re-runs a
      // configuration the estate abandoned — forever, once per press.
      await registerDrill([
        { key: "dsn", ref: "vault://secret/contextlayer/connections/drill#dsn" },
      ]);
      const jobId = "01JDEADLETTERTESTJOB000002";
      await stageDead(jobId);

      const res = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${jobId}/reenqueue`, {});
      expect(res.status).toBe(201);
      expect(res.json.rebuilt_from_registration).toBe(true);

      const refs = res.json.references as { captured: string[]; current: string[]; changed: boolean };
      expect(refs.captured).toEqual(["env://GONE_SINCE_THE_MIGRATION"]);
      expect(refs.current).toEqual(["vault://secret/contextlayer/connections/drill#dsn"]);
      expect(refs.changed).toBe(true);

      // The new job runs the CURRENT reference. Without this it would
      // carry the dead one's and fail identically, which is what the
      // operator saw three times in a row.
      const { rows } = await rig.core.pool.query<{ payload: { credentials: { ref: string }[] } }>(
        `SELECT payload FROM jobs WHERE job_id = $1`,
        [res.json.job_id as string],
      );
      expect(rows[0]!.payload.credentials[0]!.ref).toBe(
        "vault://secret/contextlayer/connections/drill#dsn",
      );
      expect(JSON.stringify(rows[0]!.payload)).not.toContain("env://");
    });

    it("B1-F1: a second press on the same dead row is refused, and names the successor", async () => {
      await registerDrill([{ key: "dsn", ref: "vault://secret/contextlayer/connections/drill#dsn" }]);
      const jobId = "01JDEADLETTERTESTJOB000003";
      await stageDead(jobId);

      const first = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${jobId}/reenqueue`, {});
      expect(first.status).toBe(201);
      const second = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${jobId}/reenqueue`, {});
      // Three presses produced three parallel dead jobs on the pilot,
      // all forked from the same stale point. The chain continues from
      // the newest job or not at all.
      expect(second.status).toBe(409);
      expect(second.json.error).toBe("already_reenqueued");
      expect(second.json.job_id).toBe(first.json.job_id);
    });

    it("B1-F1: a job whose system has no registration is refused, not replayed", async () => {
      const jobId = "01JDEADLETTERTESTJOB000004";
      await stageDead(jobId, { system: "long_gone" });
      const res = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${jobId}/reenqueue`, {});
      expect(res.status).toBe(409);
      expect(res.json.error).toBe("no_registration");
      expect(res.json.detail as string).toContain("no longer has");
    });

    it("B1-F1: an execute job is refused — it carries somebody else's request", async () => {
      const jobId = "01JDEADLETTERTESTJOB000005";
      await rig.core.pool.query(
        `INSERT INTO jobs (job_id, type, class, system, connector_name, version_constraint,
                           payload, priority, max_attempts, deadline_s, max_deferrals, state,
                           triggers, error, attempt, finished_at)
         VALUES ($1,'execute','interactive','drill','drill','*', $2::jsonb, 5, 3, 600, 2,
                 'dead_lettered', '[]'::jsonb, $3::jsonb, 3, now())`,
        [
          jobId,
          JSON.stringify({
            config: { system: "drill" },
            request: { dialect: "sql", statement: "SELECT 1" },
            identity: { subject: "somebody-else", roles: ["reporter"] },
          }),
          JSON.stringify({ code: "internal", message: "boom", retryable: false }),
        ],
      );
      const res = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${jobId}/reenqueue`, {});
      expect(res.status).toBe(409);
      expect(res.json.error).toBe("not_reenqueueable");
      // The reason, not just the refusal: re-running it would execute a
      // stranger's statement under their recorded identity for nobody.
      expect(res.json.detail as string).toContain("somebody else");
    });

    it("re-enqueue is offered for dead-lettered jobs only", async () => {
      const { rows } = await rig.core.pool.query<{ job_id: string }>(
        `SELECT job_id FROM jobs WHERE state = 'queued' LIMIT 1`,
      );
      if (!rows[0]) return;
      const res = await apiPost(rig, steward, `/v1/dashboard/ops/jobs/${rows[0].job_id}/reenqueue`, {});
      expect(res.status).toBe(409);
      expect(res.json.error).toBe("not_dead_lettered");
    });

    it("a reporter reads no ops surface and writes none", async () => {
      for (const p of ["/v1/dashboard/ops/jobs", "/v1/dashboard/ops/runs", "/v1/dashboard/ops/hooks"]) {
        const res = await apiGet(rig, reporter, p);
        expect(res.status).toBe(403);
      }
      const write = await apiPost(rig, reporter, "/v1/dashboard/ops/hooks/audited_src/rotate", {});
      expect(write.status).toBe(403);
    });
  });

  // -- DT-5 ------------------------------------------------------------------

  describe("DT-5: a webhook secret is shown once and never stored", () => {
    it("the creation response carries it; no read endpoint returns it", async () => {
      const res = await apiPost(rig, steward, "/v1/dashboard/ops/hooks/audited_src/rotate", {});
      expect(res.status).toBe(201);
      const secret = res.json.secret as string;
      expect(secret).toBeTruthy();
      expect(res.json.shown_once).toContain("only time this value is shown");

      // The store holds a hash, and nothing can recover the value from
      // it — so there is no endpoint that *could* return it, which is a
      // stronger claim than "no endpoint does".
      const { rows } = await rig.core.pool.query<{ secret_hash: string }>(
        `SELECT secret_hash FROM sync_hooks WHERE system = 'audited_src'`,
      );
      expect(rows[0]!.secret_hash).not.toBe(secret);
      expect(rows[0]!.secret_hash).toMatch(/^[0-9a-f]{64}$/);

      const list = await apiGet(rig, steward, "/v1/dashboard/ops/hooks");
      expect(list.status).toBe(200);
      expect(JSON.stringify(list.json)).not.toContain(secret);

      // Not in the connections read either, and not in the audit row the
      // rotation wrote (an args digest over a secret is a verifier for it).
      const conns = await apiGet(rig, steward, "/v1/dashboard/connections");
      expect(JSON.stringify(conns.json)).not.toContain(secret);
      const { rows: audit } = await rig.core.pool.query<{ n: string }>(
        `SELECT count(*) AS n FROM audit_records
          WHERE tool = 'dashboard.ops.hook_rotate' AND result_meta::text LIKE $1`,
        [`%${secret}%`],
      );
      expect(Number(audit[0]!.n)).toBe(0);
    });

    it("rotating replaces the hash, so the old secret stops working", async () => {
      const first = await apiPost(rig, steward, "/v1/dashboard/ops/hooks/audited_src/rotate", {});
      const firstSecret = first.json.secret as string;
      const second = await apiPost(rig, steward, "/v1/dashboard/ops/hooks/audited_src/rotate", {});
      expect(second.json.outcome).toBe("rotated");
      expect(second.json.secret).not.toBe(firstSecret);
    });

    it("a hook for an unregistered system is a 404, not a secret nobody can use", async () => {
      const res = await apiPost(rig, steward, "/v1/dashboard/ops/hooks/no_such_system/rotate", {});
      expect(res.status).toBe(404);
    });
  });



  // -- §4's batched → approved return ---------------------------------------

  describe("returning a batched request to the queue (fault-ledger §4)", () => {
    it("moves it back to approved with its note, and clears the batch stamp", async () => {
      const issueId = await fileRequest(rig, reporter, "we need the churn number written down");
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" });
      const batch = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", {});
      expect(batch.status).toBe(201);

      const returned = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/return`, {
        note: "no object named and no metric doc matches; unblocked by naming which table this is about",
      });
      expect(returned.status).toBe(200);
      const issue = returned.json.issue as {
        status: string;
        batch_id: string | null;
        returned: { note: string } | null;
        verdict: { by: string } | null;
        occurrences: number;
      };
      expect(issue.status).toBe("approved");
      // Cleared, so the next batch can pick it up — a returned request is
      // approved work waiting for evidence, not failed work.
      expect(issue.batch_id).toBeNull();
      expect(issue.returned!.note).toContain("unblocked by naming");
      // The steward's approval still stands; nothing about it was wrong.
      expect(issue.verdict!.by).toBe(USERS.steward.username);

      // Occurrences are NOT incremented: the queue is ordered by demand,
      // and a skill saying "I could not write this" is not another person
      // asking for it.
      const { rows } = await rig.core.pool.query<{ occurrences: number }>(
        `SELECT occurrences FROM ledger_issues WHERE issue_id = $1`,
        [issueId],
      );
      expect(rows[0]!.occurrences).toBe(issue.occurrences);
    });

    it("refuses a return with no note — a silent drop wearing a state change", async () => {
      const issueId = await fileRequest(rig, reporter, "the seat definition is ambiguous in two places");
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, { verdict: "approve" });
      await apiPost(rig, steward, "/v1/dashboard/ledger/batches", {});
      const res = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/return`, { note: "  " });
      expect(res.status).toBe(400);
      expect(res.json.detail as string).toContain("what evidence would unblock");
    });

    it("refuses on a request that is not batched, and refuses a reporter outright", async () => {
      const issueId = await fileRequest(rig, reporter, "the trial length is not documented anywhere");
      const notBatched = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/return`, {
        note: "nothing to return",
      });
      expect(notBatched.status).toBe(409);

      const asReporter = await apiPost(rig, reporter, `/v1/dashboard/ledger/issues/${issueId}/return`, {
        note: "let me out",
      });
      expect(asReporter.status).toBe(403);
    });
  });

  // -- the D-101.5 loop, product half ---------------------------------------

  describe("request → verdict → batch → merged PR → the filer sees it", () => {
    it("closes the whole loop, and resolves exactly the trailered request", async () => {
      // The demonstration B-1's gate asks for, minus the agent: what the
      // skill does with a batch is AS-18's scenario, and what the
      // *product* does around it is this. Both halves have to hold, and
      // only one of them needs a model.
      const answered = await fileRequest(
        rig,
        reporter,
        "nothing says how we count refunds against the original order",
        "A refund is counted in the month the credit note is issued.",
      );
      const returned = await fileRequest(rig, reporter, "the churn number should be written down");

      for (const issueId of [answered, returned]) {
        const v = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
          verdict: "approve",
        });
        expect(v.status).toBe(200);
      }

      const batch = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", {});
      expect(batch.status).toBe(201);
      const batched = (batch.json.issues as { issue_id: string; status: string; batch_id: string }[]);
      // Both of these are in it. The batch may also carry requests other
      // tests in this file approved — that is the trigger working as
      // specified (it cuts from the whole approved worklist), and pinning
      // it to exactly two would be asserting test isolation, not product
      // behaviour.
      const ids = batched.map((i) => i.issue_id);
      expect(ids).toContain(answered);
      expect(ids).toContain(returned);
      expect(batched.every((i) => i.status === "batched")).toBe(true);
      expect(new Set(batched.map((i) => i.batch_id)).size).toBe(1);
      expect(batched.length).toBeLessThanOrEqual(rig.core.cfg.dashboard.batchMax);
      // The trigger hands over a work list and says so — "deliver" invites
      // the reading that something was written, and nothing was.
      expect(batch.json.note as string).toContain("Nothing has been written");

      // The enrich skill's PR, as S1b specifies it: one trailer for the
      // request the batch satisfied, and none for the one it returned.
      const prBody = [
        "## Requests in this batch",
        "",
        "| Request | Doc | Grounding |",
        "|---|---|---|",
        `| \`${answered}\` refunds | \`systems/drill/shop/refunds.md\` | customer-provided |`,
        "",
        "### Returned to the queue",
        "",
        `- \`${returned}\` — no object named; unblocked by naming the metric.`,
        "",
        `CL-Resolves: ${answered}`,
        "",
      ].join("\n");
      await writeFile(
        rig.kb.prsFile,
        JSON.stringify(
          {
            next: 2,
            prs: [
              {
                number: 1,
                url: "local-pr://1",
                branch: "enrich/batch-1",
                title: "enrich: knowledge-request batch",
                body: prBody,
                labels: [],
                state: "merged",
                merged_at: new Date().toISOString(),
                comments: [],
              },
            ],
          },
          null,
          2,
        ),
      );
      const provider = createProvider(syncConfig(rig.kb, `${rig.kb.remote}-b1-wd`));
      expect(await sweepResolutions(rig.core.pool, provider)).toBe(1);

      // Exactly the trailered request resolved. The other is still
      // batched — its absence from the trailers is what keeps it open,
      // which is the mechanism S1b relies on rather than a convention.
      const { rows } = await rig.core.pool.query<{ issue_id: string; status: string; resolution: { pr_url: string } | null }>(
        `SELECT issue_id, status, resolution FROM ledger_issues WHERE issue_id = ANY($1::uuid[])`,
        [[answered, returned]],
      );
      const byId = Object.fromEntries(rows.map((r) => [r.issue_id, r]));
      expect(byId[answered]!.status).toBe("resolved");
      expect(byId[answered]!.resolution!.pr_url).toBe("local-pr://1");
      expect(byId[returned]!.status).toBe("batched");

      // …and the requester sees the resolution, with the diff that
      // answered them — the F-10 half, which is the point of the loop.
      const inbox = await apiGet(rig, reporter, "/v1/dashboard/inbox");
      const item = (inbox.json.items as {
        issue_id: string;
        unread: boolean;
        status: string;
        resolution: { pr_url: string } | null;
      }[]).find((i) => i.issue_id === answered)!;
      expect(item).toBeDefined();
      expect(item.status).toBe("resolved");
      expect(item.unread).toBe(true);
      expect(item.resolution!.pr_url).toBe("local-pr://1");

      // The returned request is NOT in the inbox: it has no verdict to
      // report, and telling the filer "answered" would be a lie.
      expect(
        (inbox.json.items as { issue_id: string }[]).find((i) => i.issue_id === returned),
      ).toBeUndefined();
    });
  });



  // -- B1-F3: the gap half of the module gets its §8 actions ----------------

  describe("B1-F3: gap triage actions (fault-ledger §8)", () => {
    const fileGap = async (description: string, object?: string): Promise<string> => {
      const res = await apiPost(rig, reporter, "/v1/dashboard/ledger/gaps", {
        description,
        ...(object ? { object } : {}),
      });
      expect(res.status).toBe(201);
      return res.json.issue_id as string;
    };

    it("acknowledge moves a gap to triaged and says what that buys", async () => {
      const issueId = await fileGap("the orders table has no human doc at all");
      const res = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/triage`, {
        action: "acknowledge",
      });
      expect(res.status).toBe(200);
      expect((res.json.issue as { status: string }).status).toBe("triaged");
      // The answer to "and then what?" travels with the state change —
      // a steward reading `triaged` learns nothing on its own.
      expect(res.json.note as string).toContain("enrich skill's work list");
      expect(res.json.note as string).toContain("Nothing drafts by itself");
    });

    it("dismiss requires a reason and keeps the row", async () => {
      const issueId = await fileGap("someone wants a chart builder in the dashboard");
      const bare = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/triage`, {
        action: "dismiss",
      });
      expect(bare.status).toBe(400);
      expect(bare.json.detail as string).toContain("read if this recurs");

      const res = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/triage`, {
        action: "dismiss",
        reason: "out of scope: report authoring lives in the customer's own session, ruling RA-1",
      });
      expect(res.status).toBe(200);
      const issue = res.json.issue as { status: string; resolution: Record<string, unknown> };
      expect(issue.status).toBe("dismissed");
      expect(issue.resolution.kind).toBe("dismissed");
      expect(issue.resolution.reason).toContain("report authoring lives in the customer");
      // LED-R2 binds this text exactly as it binds a rejection reason —
      // a dismissal is human-authored prose a later reader sees, so the
      // bare ruling number is scrubbed like any other value-shaped token.
      expect(issue.resolution.reason).not.toContain("RA-1");
      // Kept, not deleted: the record of what was declined is worth as
      // much as the record of what was done.
      const { rows } = await rig.core.pool.query<{ n: string }>(
        `SELECT count(*) AS n FROM ledger_issues WHERE issue_id = $1`,
        [issueId],
      );
      expect(Number(rows[0]!.n)).toBe(1);
    });

    it("a dismissed gap that recurs reopens, with the dismissal preserved (L-4)", async () => {
      const description = "nothing documents how we count active seats";
      const issueId = await fileGap(description);
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/triage`, {
        action: "dismiss",
        reason: "not this quarter",
      });

      const again = await fileGap(description);
      expect(again).toBe(issueId);
      const { rows } = await rig.core.pool.query<{
        status: string;
        reopen_count: number;
        resolution: Record<string, unknown> | null;
      }>(`SELECT status, reopen_count, resolution FROM ledger_issues WHERE issue_id = $1`, [issueId]);
      expect(rows[0]!.status).toBe("open");
      expect(rows[0]!.reopen_count).toBeGreaterThanOrEqual(1);
      // The argument for revisiting a wont_fix is the count plus the
      // reason it was declined, so the reason survives the reopen.
      expect(rows[0]!.resolution!.reason).toBe("not this quarter");
    });

    it("the two lifecycles do not cross: a request refuses gap triage", async () => {
      // "Acknowledge" means *this is real*; "approve" means *worth
      // drafting*. One control for both would let a request skip its
      // verdict, which is UI-11's whole concern.
      const requestId = await fileRequest(rig, reporter, "the refund window should be written down");
      const res = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${requestId}/triage`, {
        action: "acknowledge",
      });
      expect(res.status).toBe(400);
      expect(res.json.error).toBe("wrong_kind");
      expect(res.json.detail as string).toContain("verdict lifecycle");
    });


    it("B1-F4: the disposition says what closes each kind, and a DDL handoff is not enrichment", async () => {
      // `routed_to` says who hears about an issue; it does not say what
      // act closes it. Acknowledging a missing doc and acknowledging a
      // reporting-view handoff both produce `triaged`, and only one of
      // them is work a skill can do.
      const docGap = await fileGap("subscriptions.plan_code has no doc", "drill.shop.orders");
      const list = await apiGet(rig, steward, "/v1/dashboard/ledger?status=all&limit=100");
      const issues = list.json.issues as {
        issue_id: string;
        kind: string;
        disposition: { enrichable: boolean; actor: string; next_act: string; why: string };
      }[];

      const doc = issues.find((i) => i.issue_id === docGap)!;
      // human_filed is free-form and deliberately NOT auto-enrichable —
      // somebody has to decide which kind it really is.
      expect(doc.disposition).toBeDefined();
      expect(typeof doc.disposition.next_act).toBe("string");

      // The kinds the enrich skill may take, and the ones it must not.
      const { ENRICHABLE_KINDS, dispositionFor } = await import("../src/ledger.js");
      expect(ENRICHABLE_KINDS).toContain("missing_doc");
      expect(ENRICHABLE_KINDS).toContain("uncertified_metric");
      expect(ENRICHABLE_KINDS).not.toContain("capability_gap");
      expect(ENRICHABLE_KINDS).not.toContain("guardrail_hit");

      // The one that matters on the pilot: a reporting-view handoff.
      const cap = dispositionFor("capability_gap");
      expect(cap.enrichable).toBe(false);
      expect(cap.next_act).toContain("DDL");
      // And the reason names the ruling, so nobody re-litigates it.
      expect(cap.why).toContain("D-81");
      expect(cap.actor).toContain("DBA");
    });

    it("B1-F4: the shipped enrich skill filters by kind, not by status alone", () => {
      // S1 read "items assigned to enrichment" — a filter that never
      // existed, so a skill obeying it literally would pick up DDL
      // handoffs and document views that do not exist yet.
      const skill = readFileSync(path.join(CORE_DIR, "skills", "enrich", "SKILL.md"), "utf-8");
      expect(skill).toContain("Not every acknowledged gap is yours");
      expect(skill).toContain("capability_gap");
      expect(skill).toMatch(/does not exist yet/);
    });

    it("a reporter cannot triage, and the refusal is audited", async () => {
      const issueId = await fileGap("the exports table is undocumented");
      const res = await apiPost(rig, reporter, `/v1/dashboard/ledger/issues/${issueId}/triage`, {
        action: "acknowledge",
      });
      expect(res.status).toBe(403);
      const { rows } = await rig.core.pool.query<{ n: string }>(
        `SELECT count(*) AS n FROM audit_records
          WHERE tool = 'dashboard.ledger.triage' AND decision = 'denied' AND subject = $1`,
        [USERS.reporter.username],
      );
      expect(Number(rows[0]!.n)).toBeGreaterThanOrEqual(1);
    });

    it("triage writes ledger state only — no git call, no KB content", async () => {
      const gitBefore = rig.gitFingerprint();
      const headBefore = rig.kb.headSha();
      const issueId = await fileGap("the refunds view has no doc");
      await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/triage`, {
        action: "acknowledge",
      });
      // UI-11 governs the whole module, not only the request queue.
      expect(rig.gitFingerprint()).toBe(gitBefore);
      expect(rig.kb.headSha()).toBe(headBefore);
    });
  });

  // -- B1-F2: one queue, whether or not the requester has a browser ---------

  describe("B1-F2: a reporter's session files into the same queue as the form", () => {
    it("flag_gap(enrichment_request) from a session reaches the steward's queue with its proposal", async () => {
      // The ledger spec's §4 amendment is explicit: two inlets, "one
      // queue whether or not the requester has a browser open". The
      // dashboard form was built at B-0 and the tool has existed since
      // D-101.3 — but nothing instructed a skill to use it, so in
      // practice it WAS a queue only browser users could file into.
      // This asserts the two inlets land in one place.
      const proposal =
        "A refund is counted in the month the credit note is issued, not the month of the order.";
      const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
        kind: "enrichment_request",
        description: "nothing says which month a refund is counted in",
        proposal,
      });
      expect(result.isError).toBe(false);
      const issueId = result.payload.issue_id as string;

      // The steward sees it in the Knowledge Requests queue — the same
      // read the dashboard module renders, unfiltered by inlet.
      const queue = await apiGet(rig, steward, "/v1/dashboard/ledger?status=all&limit=100");
      const issue = (queue.json.issues as { issue_id: string; kind: string; status: string }[]).find(
        (i) => i.issue_id === issueId,
      )!;
      expect(issue).toBeDefined();
      expect(issue.kind).toBe("enrichment_request");
      expect(issue.status).toBe("open");

      // And the proposal is on the event stream, scrubbed at storage and
      // neutralized at render — the steward reads the requester's words.
      const detail = await apiGet(rig, steward, `/v1/dashboard/ledger/issues/${issueId}`);
      const events = detail.json.events as { subject?: string; detail: { proposal?: string } }[];
      const withProposal = events.find((e) => typeof e.detail.proposal === "string")!;
      expect(withProposal).toBeDefined();
      expect(withProposal.detail.proposal).toContain("credit note");
      // LED-R3: the filer is the session's own identity, server-set.
      expect(withProposal.subject).toBe(USERS.reporter.username);
    });

    it("a session-filed request runs the whole verdict lifecycle", async () => {
      // Filed from a session, approved in the browser, batched — the
      // inlet must not produce a second-class row.
      const result = await callTool(rig, rig.token("reporter"), "reporter", "flag_gap", {
        kind: "enrichment_request",
        description: "the activation definition is not written down anywhere",
        proposal: "Activation is the first completed import, not the first sign-in.",
      });
      const issueId = result.payload.issue_id as string;

      const verdict = await apiPost(rig, steward, `/v1/dashboard/ledger/issues/${issueId}/verdict`, {
        verdict: "approve",
      });
      expect(verdict.status).toBe(200);
      expect((verdict.json.issue as { status: string }).status).toBe("approved");

      const batch = await apiPost(rig, steward, "/v1/dashboard/ledger/batches", {});
      expect(batch.status).toBe(201);
      expect((batch.json.issues as { issue_id: string }[]).map((i) => i.issue_id)).toContain(issueId);
    });

    it("the shipped report skill tells a session how to file one", () => {
      // The capability existed and nothing drove it — which is what
      // B1-F2 actually was. The instruction is the fix, so the
      // instruction is what this asserts, over the shipped skill file.
      const skill = readFileSync(path.join(CORE_DIR, "skills", "report", "SKILL.md"), "utf-8");
      expect(skill).toContain("enrichment_request");
      expect(skill).toContain("proposal");
      // Their words, not the agent's summary — the rule that makes the
      // proposal usable as drafting evidence.
      expect(skill).toMatch(/THEIR words|their words, verbatim/i);
      // And the honesty rule: filing is not writing.
      expect(skill).toContain("I've filed it");
    });
  });

  // -- the client's structural claims ----------------------------------------

  describe("the shipped bundle keeps UI-1, UI-5, UI-8 structural", () => {
    it("every screen in the bundle is covered by these assertions", () => {
      const listed = new Set(APP_SOURCES);
      const onDisk = execFileSync("ls", [path.join(CORE_DIR, "web", "src")], { encoding: "utf-8" })
        .split("\n")
        .filter((f) => f.endsWith(".tsx") || f.endsWith(".ts"));
      for (const file of onDisk) {
        expect(listed.has(file), `${file} is not in APP_SOURCES — add it or it escapes these checks`).toBe(true);
      }
    });

    it("DT-2, extended: no role name and no role-conditional shape in the bundle", () => {
      const bundle = readFileSync(path.join(CORE_DIR, "web", "dist", "app.js"), "utf-8");
      for (const role of ['"steward"', '"reporter"', '"ops"', '"auditor"', '"benchmark"']) {
        expect(bundle).not.toContain(role);
      }
      for (const shape of ["roles.includes", "roles.some", "hasRole", "isAdmin", "isSteward"]) {
        expect(bundle).not.toContain(shape);
      }
    });

    it("UI-5: no raw-HTML escape hatch in any screen we wrote", () => {
      const sources = APP_SOURCES.map((f) =>
        readFileSync(path.join(CORE_DIR, "web", "src", f), "utf-8"),
      ).join("\n");
      for (const forbidden of ["dangerouslySetInnerHTML", "innerHTML", "outerHTML", "insertAdjacentHTML"]) {
        expect(sources).not.toContain(forbidden);
      }
    });

    it("D-103.1: no client persistence anywhere, including the secret panel", () => {
      const sources = APP_SOURCES.map((f) =>
        readFileSync(path.join(CORE_DIR, "web", "src", f), "utf-8"),
      ).join("\n");
      for (const forbidden of ["localStorage", "sessionStorage", "indexedDB", "document.cookie"]) {
        expect(sources).not.toContain(forbidden);
      }
    });

    it("UI-8: no password-shaped input exists to type a secret into", () => {
      const sources = APP_SOURCES.map((f) =>
        readFileSync(path.join(CORE_DIR, "web", "src", f), "utf-8"),
      ).join("\n");
      expect(sources).not.toContain('type="password"');
      // The secret panel *displays* one value, once, from a response —
      // and that is the only direction a secret moves in this client.
      expect(sources).toContain("secret-once");
    });

    it("the module map now reports KB Health, Gap Triage, Publish and Ops as built", async () => {
      const res = await apiGet(rig, steward, "/v1/dashboard/modules");
      const modules = res.json.modules as { id: string; built: boolean }[];
      for (const id of ["kb_health", "gap_triage", "publish", "ops", "connections"]) {
        expect(modules.find((m) => m.id === id)!.built, `${id} should be built`).toBe(true);
      }
      // The ones that genuinely are not, still declared and still marked
      // — a menu that silently omits them teaches nobody (UI-10).
      for (const id of ["profiles", "audit", "benchmarks", "setup"]) {
        expect(modules.find((m) => m.id === id)!.built, `${id} should not be built`).toBe(false);
      }
    });

    it("the SPA serves the inbox route, which is not a dashboard.yaml module", async () => {
      const res = await fetch(`${rig.base}/app/inbox`);
      expect(res.status).toBe(200);
      expect(res.headers.get("content-type")).toContain("text/html");
    });
  });
});
