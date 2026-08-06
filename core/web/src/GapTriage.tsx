/**
 * Gap Triage & Knowledge Requests (dashboard spec §3, checkpoint B-1).
 *
 * Two queues over one ledger: the detector-and-human gap queue, and the
 * knowledge-request queue whose verdict lifecycle D-101.2 added. Both
 * are ordered by the server on `(occurrences, distinct_subjects)` — the
 * argument the queue already has, since eleven people asking for the
 * same doc is the strongest case for writing it — and this file does not
 * re-sort them.
 *
 * **This screen adds no authority** (D-114.7). Every control it renders
 * is rendered for everybody, because a hidden button teaches nobody why
 * it is hidden and a client that hides it is a client that decided
 * (UI-1). A caller without the steward profile presses Approve and reads
 * the server's own 403. DT-11 is proven at the server and re-run through
 * this exact call shape so the two cannot drift.
 *
 * **A verdict is not content** (UI-11). Approve means *worth drafting*;
 * it writes ledger state, makes no git call, and puts nothing in the
 * knowledge base. The screen says so where the button is, not in a
 * document nobody opens — and "deliver batch" says the same thing again,
 * because the word "deliver" invites the other reading.
 *
 * **The proposal is quoted, never adopted** (D-114.8, DT-12). It renders
 * through `<Text>` like every server string — already scrubbed at storage
 * (LED-R2) and neutralized at the render boundary (LED-R5) — and it is
 * labelled as the requester's words rather than shown in the product's
 * own voice, because chrome reads as endorsement unless something says
 * otherwise.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  api,
  type ApiError,
  type Batch,
  type Issue,
  type IssueDetail,
  type IssueList,
  type LedgerEvent,
} from "./api";
import { Dark, ServerSays, Spinner, Text } from "./ui";

const REQUEST_KIND = "enrichment_request";

function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return String(iso);
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/** The status word, with the sentence that makes it mean something. */
const STATUS_NOTE: Record<string, string> = {
  open: "waiting for a verdict",
  triaged: "acknowledged, not yet resolved",
  approved: "worth drafting — waiting to be cut into a batch",
  batched: "handed to the enrich skill; a pull request is being drafted",
  rejected: "declined, with a reason the filer can read",
  resolved: "a merged pull request answered it",
  dismissed: "closed without a change",
};

function StatusPill({ issue }: { issue: Issue }) {
  return (
    <span className={`pill pill-${issue.status}`}>
      <Text value={issue.status} />
    </span>
  );
}

/**
 * The proposal, quoted. Its own frame and its own label: this is the
 * requester's text, not the estate's, and the difference is the whole of
 * UI-11's first sentence.
 */
function Proposal({ text, from }: { text: string; from?: string | null }) {
  return (
    <div className="proposal">
      <div className="proposal-label">
        The requester&apos;s proposed content{from ? <> — from <Text value={from} /></> : null}, quoted.
        It is drafting input, not knowledge-base content: if this request is approved and drafted,
        the doc is written in the KB&apos;s own voice and <em>cites</em> this submission rather than
        containing it.
      </div>
      <blockquote>
        <Text value={text} />
      </blockquote>
    </div>
  );
}

function EventStream({ events }: { events: LedgerEvent[] }) {
  if (events.length === 0) return <p className="muted">No events recorded on this issue.</p>;
  return (
    <ol className="event-stream">
      {events.map((event) => {
        const proposal = typeof event.detail?.proposal === "string" ? event.detail.proposal : null;
        return (
          <li key={event.event_id}>
            <div className="event-head">
              <span className="muted">{when(event.ts)}</span>
              <code>
                <Text value={event.kind} />
              </code>
              <span className="muted">
                class <Text value={event.detector_class} />
                {event.subject ? (
                  <>
                    {" · "}
                    <Text value={event.subject} />
                  </>
                ) : null}
                {event.profile ? (
                  <>
                    {" · "}
                    <Text value={event.profile} />
                  </>
                ) : null}
              </span>
            </div>
            {event.description && (
              <p className="event-desc">
                <Text value={event.description} />
              </p>
            )}
            {proposal && <Proposal text={proposal} from={event.subject ?? null} />}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The verdict controls (UI-11).
 *
 * Rendered for every caller. Rejection requires a reason here because it
 * requires one at the server — a rejection the filer cannot read is a
 * disappearance, not a decision — and the `required` attribute below is
 * a courtesy over that server rule, never the rule itself.
 */
function Verdict({
  issue,
  csrf,
  onDone,
}: {
  issue: Issue;
  csrf: string | null;
  onDone: () => void;
}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const cast = async (verdict: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    const res = await api.post(
      `/v1/dashboard/ledger/issues/${encodeURIComponent(issue.issue_id)}/verdict`,
      verdict === "reject" ? { verdict, reason } : { verdict },
      csrf,
    );
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setRejecting(false);
    setReason("");
    onDone();
  };

  return (
    <div className="verdict">
      <p className="muted small">
        Approving means <strong>worth drafting</strong> — it changes this request&apos;s state in the
        ledger and nothing else. No document is written, no pull request is opened, and nothing is
        certified: that happens when a person merges a reviewed diff under their own name.
      </p>
      <div className="actions">
        <button onClick={() => cast("approve")} disabled={busy}>
          {busy ? <Spinner label="recording…" /> : "Approve — worth drafting"}
        </button>
        {rejecting ? (
          <button onClick={() => setRejecting(false)}>Cancel</button>
        ) : (
          <button onClick={() => setRejecting(true)}>Reject…</button>
        )}
      </div>
      {rejecting && (
        <form
          className="reject-form"
          onSubmit={(e) => {
            e.preventDefault();
            void cast("reject");
          }}
        >
          <label>
            Reason — the person who filed this will read it
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              required
              placeholder="Why this is not worth drafting, in terms the filer can act on or argue with."
            />
          </label>
          <button type="submit" disabled={busy || !reason.trim()}>
            Reject with this reason
          </button>
        </form>
      )}
      {error && <ServerSays error={error} />}
    </div>
  );
}


/**
 * The gap actions (fault-ledger §8, finding B1-F3).
 *
 * B-1 first shipped this queue read-only — a steward could read a gap
 * and do nothing with it, which is most of a triage screen missing. Two
 * acts, and the panel says what each one *buys*, because "triaged" on
 * its own tells nobody what happens next and the honest answer —
 * *nothing happens by itself, you run the skill* — is exactly the sort
 * of thing a product hides by accident.
 */
function Triage({ issue, csrf, onDone }: { issue: Issue; csrf: string | null; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [dismissing, setDismissing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const act = async (action: "acknowledge" | "dismiss") => {
    setBusy(true);
    setError(null);
    const res = await api.post<{ note: string }>(
      `/v1/dashboard/ledger/issues/${encodeURIComponent(issue.issue_id)}/triage`,
      action === "dismiss" ? { action, reason } : { action },
      csrf,
    );
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setNote(res.data.note);
    setDismissing(false);
    setReason("");
    onDone();
  };

  return (
    <div className="verdict">
      <div className="actions">
        {issue.status === "open" && (
          <button onClick={() => act("acknowledge")} disabled={busy}>
            {busy ? <Spinner label="recording…" /> : "Acknowledge — this is real, work it"}
          </button>
        )}
        {dismissing ? (
          <button onClick={() => setDismissing(false)}>Cancel</button>
        ) : (
          <button onClick={() => setDismissing(true)}>Dismiss…</button>
        )}
      </div>
      {/* B1-F4: what acknowledging *means* depends on the kind. A
          missing doc is work a skill can do; a reporting-view handoff is
          a DDL statement only the customer's DBA may run (D-81). Saying
          "this goes to enrich" for both was simply false for the
          second. */}
      <div className={`disposition${issue.disposition.enrichable ? " enrichable" : " manual"}`}>
        <div className="disposition-head">
          {issue.disposition.enrichable ? "A skill can close this" : "This one needs a person"}
        </div>
        <p>
          <strong>Next act:</strong> <Text value={issue.disposition.next_act} />
        </p>
        <p className="muted small">
          <strong>Who:</strong> <Text value={issue.disposition.actor} /> · <Text value={issue.disposition.why} />
        </p>
        {issue.disposition.enrichable ? (
          <p className="muted small">
            Acknowledging puts it on the enrich skill&apos;s work list. <strong>Nothing drafts by
            itself:</strong> you run <code>enrich</code> in a session, it writes the docs and opens
            one pull request, and you merge it.
          </p>
        ) : (
          <p className="muted small">
            Acknowledging records that you have seen it and it is real. It does <em>not</em> queue
            any work — no skill can close this kind, so the next move is yours.
          </p>
        )}
      </div>
      {dismissing && (
        <form
          className="reject-form"
          onSubmit={(e) => {
            e.preventDefault();
            void act("dismiss");
          }}
        >
          <label>
            Reason — kept on the issue, and read if this gap comes back
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              required
              placeholder="Why this is not worth doing. If the same gap recurs it reopens automatically and the next person reads this."
            />
          </label>
          <button type="submit" disabled={busy || !reason.trim()}>
            Dismiss with this reason
          </button>
        </form>
      )}
      {error && <ServerSays error={error} />}
      {note && <div className="saved">{note}</div>}
    </div>
  );
}

function IssueCard({
  issue,
  csrf,
  onChanged,
}: {
  issue: Issue;
  csrf: string | null;
  onChanged: () => void;
}) {
  const [detail, setDetail] = useState<IssueDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const expand = async () => {
    const next = !open;
    setOpen(next);
    if (!next || detail || loading) return;
    setLoading(true);
    const res = await api.get<IssueDetail>(
      `/v1/dashboard/ledger/issues/${encodeURIComponent(issue.issue_id)}`,
    );
    setLoading(false);
    if (!res.ok) setError(res.error);
    else setDetail(res.data);
  };

  const reload = () => {
    setDetail(null);
    onChanged();
  };

  return (
    <li className="issue">
      <div className="issue-head">
        <StatusPill issue={issue} />
        <strong>
          <Text value={issue.title} />
        </strong>
      </div>

      <div className="issue-meta muted small">
        <span title="how many times this has been filed or detected">
          <Text value={issue.occurrences} /> occurrence(s)
        </span>
        {" · "}
        <span title="how many distinct people — the count only; never who">
          <Text value={issue.distinct_subjects} /> subject(s)
        </span>
        {" · last seen "}
        {when(issue.last_seen)}
        {issue.system ? (
          <>
            {" · "}
            <Text value={issue.system} />
          </>
        ) : null}
        {issue.object_fqn ? (
          <>
            {" · "}
            <code>
              <Text value={issue.object_fqn} />
            </code>
          </>
        ) : null}
        {" · "}
        <Text value={STATUS_NOTE[issue.status] ?? issue.status} />
      </div>

      {/* D-106.5: a rejected request refiled reopens, and its prior
          verdict is deliberately kept. "Rejected before, refiled by N
          more" is the sentence the steward needs, so it is written. */}
      {issue.reopen_count > 0 && (
        <div className="reopened">
          Reopened <Text value={issue.reopen_count} /> time(s) since it was last closed
          {issue.verdict?.at ? (
            <>
              {" — previously "}
              {issue.verdict.reason ? "rejected" : "decided"} by{" "}
              <Text value={issue.verdict.by} /> {when(issue.verdict.at)}
              {issue.verdict.reason ? (
                <>
                  : &ldquo;
                  <Text value={issue.verdict.reason} />
                  &rdquo;
                </>
              ) : null}
              . The verdict is kept on purpose — you may re-reject on the spot, and the count is the
              argument for not doing so.
            </>
          ) : null}
        </div>
      )}

      {issue.verdict?.at && issue.reopen_count === 0 && (
        <div className="muted small">
          verdict by <Text value={issue.verdict.by} /> {when(issue.verdict.at)}
          {issue.verdict.reason ? (
            <>
              {" — "}
              <Text value={issue.verdict.reason} />
            </>
          ) : null}
        </div>
      )}

      {issue.batch_id && (
        <div className="muted small">
          batch <code><Text value={issue.batch_id} /></code>
        </div>
      )}

      {/* §4's `batched → approved` return. Shown as its own state
          because "approved" alone would read as never-attempted: this
          request WAS attempted, and the note is what it needs next. */}
      {issue.returned && (
        <div className="returned-note">
          <strong>Came back from a batch.</strong> The enrich skill could not draft this without
          guessing, so it returned it rather than writing prose nobody could source. What it says
          would unblock it:
          <blockquote>
            <Text value={issue.returned.note} fallback="(no note recorded)" />
          </blockquote>
          It is approved and waiting — the next batch picks it up once that evidence exists.
        </div>
      )}

      {issue.resolution && issue.resolution.kind === "dismissed" && (
        <div className="reopened">
          Dismissed by <Text value={issue.resolution.by} />
          {typeof issue.resolution.reason === "string" && issue.resolution.reason ? (
            <>
              : &ldquo;
              <Text value={issue.resolution.reason} />
              &rdquo;
            </>
          ) : null}
          . The row is kept rather than deleted — if this gap happens again it reopens itself, and
          the count is the argument for revisiting the decision.
        </div>
      )}

      {issue.resolution && typeof issue.resolution.pr_url === "string" && (
        <div className="resolved-line">
          resolved by{" "}
          <a href={issue.resolution.pr_url} target="_blank" rel="noreferrer noopener">
            the merged pull request
          </a>
        </div>
      )}

      <div className="actions">
        <button onClick={expand}>{open ? "Hide history" : "History & proposal"}</button>
      </div>

      {open && (
        <div className="issue-detail">
          {loading && <Spinner label="reading the event stream…" />}
          {error && <ServerSays error={error} />}
          {detail && <EventStream events={detail.events} />}
        </div>
      )}

      {issue.kind === REQUEST_KIND && issue.status === "open" && (
        <Verdict issue={issue} csrf={csrf} onDone={reload} />
      )}

      {/* B1-F3: gaps get their §8 actions. Different lifecycle from a
          request's, deliberately — "acknowledge" means *this is real*,
          "approve" means *worth drafting*, and one control for both
          would let a request skip its verdict. */}
      {issue.kind !== REQUEST_KIND && ["open", "triaged"].includes(issue.status) && (
        <Triage issue={issue} csrf={csrf} onDone={reload} />
      )}
    </li>
  );
}

/** File a gap, or ask for a doc. Both inlets, one form — they differ in
 * kind, and the choice is the person's, so it is a control and not a
 * guess made from the words they typed. */
function FileForm({ csrf, onFiled }: { csrf: string | null; onFiled: () => void }) {
  const [kind, setKind] = useState<"request" | "gap">("request");
  const [description, setDescription] = useState("");
  const [object, setObject] = useState("");
  const [proposal, setProposal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [filed, setFiled] = useState<{ issue_id: string; occurrences: number; routed_to: string } | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFiled(null);
    const res = await api.post<{ issue_id: string; occurrences: number; routed_to: string }>(
      kind === "request" ? "/v1/dashboard/ledger/requests" : "/v1/dashboard/ledger/gaps",
      {
        description,
        ...(object.trim() ? { object: object.trim() } : {}),
        ...(kind === "request" && proposal.trim() ? { proposal } : {}),
      },
      csrf,
    );
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setFiled(res.data);
    setDescription("");
    setObject("");
    setProposal("");
    onFiled();
  };

  return (
    <form className="add-form" onSubmit={submit}>
      <h3>Ask for something, or report a gap</h3>
      <p className="form-rule">
        Your name is taken from your session — there is no field here to type one into, and nothing
        you send can change who this is recorded under.
      </p>

      <div className="kind-choice">
        <label>
          <input type="radio" checked={kind === "request"} onChange={() => setKind("request")} />
          <span>
            <strong>Knowledge request</strong> — something the knowledge base should say and
            doesn&apos;t. Gets a steward&apos;s verdict.
          </span>
        </label>
        <label>
          <input type="radio" checked={kind === "gap"} onChange={() => setKind("gap")} />
          <span>
            <strong>Gap</strong> — something wrong or missing that you hit while working. Goes to
            the triage queue.
          </span>
        </label>
      </div>

      <label>
        What is missing, in your own words
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          required
          placeholder="Nothing says how we count refunds."
        />
      </label>
      <label>
        Object it is about (optional)
        <input
          value={object}
          onChange={(e) => setObject(e.target.value)}
          placeholder="supabase.public.orders"
          spellCheck={false}
        />
      </label>
      {kind === "request" && (
        <label>
          What it should say, if you know (optional)
          <textarea
            value={proposal}
            onChange={(e) => setProposal(e.target.value)}
            rows={4}
            placeholder="A refund is counted in the month the credit note is issued, not the month of the original order."
          />
          <span className="muted small">
            This is quoted to the steward as <em>your</em> words. If it is drafted into a document,
            the document cites you as its source — it does not copy this text in.
          </span>
        </label>
      )}

      <button type="submit" disabled={busy || !description.trim()}>
        {busy ? <Spinner label="filing…" /> : kind === "request" ? "Send request" : "File gap"}
      </button>

      {error && <ServerSays error={error} />}
      {filed && (
        <div className="saved">
          Filed. This is issue <code><Text value={filed.issue_id} /></code>, now at{" "}
          <Text value={filed.occurrences} /> occurrence(s), routed to{" "}
          <Text value={filed.routed_to} />.
          {filed.occurrences > 1 && " Somebody had already asked for this — your filing added to it."}
        </div>
      )}
    </form>
  );
}

/** The "deliver batch" trigger. Its own panel, because it acts on the
 * whole approved worklist rather than on one row. */
function DeliverBatch({ approved, csrf, onDone }: { approved: number; csrf: string | null; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [batch, setBatch] = useState<Batch | null>(null);

  const cut = async () => {
    setBusy(true);
    setError(null);
    const res = await api.post<Batch>("/v1/dashboard/ledger/batches", {}, csrf);
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setBatch(res.data);
    onDone();
  };

  return (
    <section className="panel">
      <h3>Approved worklist</h3>
      {approved === 0 ? (
        <p className="muted">
          Nothing is approved yet. Approve a request above and it appears here, waiting to be cut
          into a batch.
        </p>
      ) : (
        <p>
          <Text value={approved} /> approved request(s) are waiting to be drafted.
        </p>
      )}
      <button onClick={cut} disabled={busy || approved === 0}>
        {busy ? <Spinner label="cutting…" /> : "Deliver batch to the enrich skill"}
      </button>
      <p className="muted small">
        This stamps up to ten approved requests with one batch id and hands the enrich skill a work
        list. It drafts nothing itself, writes nothing to the knowledge base, and opens no pull
        request — the skill drafts, and a person merges.
      </p>
      {error && <ServerSays error={error} />}
      {batch && (
        <div className="saved">
          Batch <code><Text value={batch.batch_id} /></code> — <Text value={batch.count} /> request(s).{" "}
          <Text value={batch.note} />
        </div>
      )}
    </section>
  );
}


/**
 * What a steward does with a triaged queue — stated, because the queue
 * itself cannot do it and a screen that offers only verbs leaves the
 * question "and then what?" unanswered (finding B1-F3).
 *
 * The boundary being described is the product's, not a limitation: the
 * dashboard triages and never drafts, the skill drafts and never merges,
 * and a human merges. Three acts, three actors, and this panel names the
 * one the person is holding.
 */
function WorkList({ triaged }: { triaged: Issue[] }) {
  const forSkill = triaged.filter((i) => i.disposition.enrichable);
  const forYou = triaged.filter((i) => !i.disposition.enrichable);

  return (
    <section className="panel">
      <h3>Working the queue</h3>
      {triaged.length === 0 ? (
        <p className="muted">
          Nothing acknowledged yet. Acknowledge a gap above and it appears here, sorted by who can
          actually close it.
        </p>
      ) : (
        <>
          <h4>
            The enrich skill can close these <span className="count-badge">{forSkill.length}</span>
          </h4>
          {forSkill.length === 0 ? (
            <p className="muted small">
              None — everything you have acknowledged needs a person, not a skill.
            </p>
          ) : (
            <>
              <ul className="worklist">
                {forSkill.map((i) => (
                  <li key={i.issue_id}>
                    <code><Text value={i.object_fqn ?? i.kind} /></code>{" "}
                    <span className="muted"><Text value={i.title} /></span>
                  </li>
                ))}
              </ul>
              <p className="muted small">
                Open a Claude Code session with your steward bundle and ask it to run the{" "}
                <code>enrich</code> skill over the acknowledged ledger items. It grounds each claim
                in evidence it can cite and opens one pull request; you review that diff and merge
                it — the merge is what certifies, and nothing here can do it for you.
              </p>
            </>
          )}

          <h4>
            These need you <span className="count-badge">{forYou.length}</span>
          </h4>
          {forYou.length === 0 ? (
            <p className="muted small">None.</p>
          ) : (
            <ul className="worklist">
              {forYou.map((i) => (
                <li key={i.issue_id} className="stacked">
                  <span>
                    <code><Text value={i.object_fqn ?? i.kind} /></code>{" "}
                    <span className="muted"><Text value={i.title} /></span>
                  </span>
                  <span className="muted small">
                    → <Text value={i.disposition.next_act} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export function GapTriage({ csrf }: { csrf: string | null }) {
  const [list, setList] = useState<IssueList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"requests" | "gaps">("requests");

  const load = useCallback(async () => {
    // `status=all` so a screen showing the queue also shows what left it:
    // the approved worklist, the batch in flight and the recent verdicts
    // are the steward's own record of what they decided.
    const res = await api.get<IssueList>("/v1/dashboard/ledger?status=all&limit=100");
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      setList(null);
      return;
    }
    setError(null);
    setList(res.data);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner label="reading the ledger…" />;
  if (error) return <ServerSays error={error} />;
  if (!list) return null;

  const requests = list.issues.filter((i) => i.kind === REQUEST_KIND);
  const gaps = list.issues.filter((i) => i.kind !== REQUEST_KIND);
  const approved = requests.filter((i) => i.status === "approved").length;
  const triagedGaps = gaps.filter((i) => i.status === "triaged");
  const shown = tab === "requests" ? requests : gaps;

  return (
    <div className="gap-triage">
      {list.scope.role_scope === "self" && (
        <div className="notice">
          You are seeing <strong>the requests and gaps you filed</strong>. The server scopes this
          queue to your own identity; a steward sees the estate&apos;s.
        </div>
      )}

      <div className="tabs">
        <button className={tab === "requests" ? "active" : ""} onClick={() => setTab("requests")}>
          Knowledge requests <span className="count-badge">{requests.length}</span>
        </button>
        <button className={tab === "gaps" ? "active" : ""} onClick={() => setTab("gaps")}>
          Gap triage <span className="count-badge">{gaps.length}</span>
        </button>
      </div>

      {shown.length === 0 ? (
        <Dark
          title={tab === "requests" ? "No knowledge requests" : "No gaps in the queue"}
          why={
            tab === "requests"
              ? "Nobody has asked for anything yet — through this form or through a session's flag_gap. Nothing here is hidden from you; there is nothing to show."
              : "No detector has fired and nobody has filed a gap. This is the ledger's real state."
          }
        />
      ) : (
        <ul className="issue-list">
          {shown.map((issue) => (
            <IssueCard key={issue.issue_id} issue={issue} csrf={csrf} onChanged={load} />
          ))}
        </ul>
      )}

      {tab === "gaps" && gaps.length > 0 && <WorkList triaged={triagedGaps} />}

      {tab === "requests" && <DeliverBatch approved={approved} csrf={csrf} onDone={load} />}

      <FileForm csrf={csrf} onFiled={load} />
    </div>
  );
}
