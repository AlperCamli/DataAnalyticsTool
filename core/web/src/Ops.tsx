/**
 * Ops (dashboard spec §3, U-10 / U-11, checkpoint B-1).
 *
 * Run and job health, the dead-letter queue with re-enqueue, and webhook
 * secret rotation. Three things about this screen are rules rather than
 * choices.
 *
 * **Re-enqueue does not repair.** The button enqueues a *new* job with
 * the dead one's payload, under the pressing user's identity. The dead
 * row keeps its error and its terminal state, because it is the evidence
 * that something failed — and this screen says that where the button is.
 *
 * **A secret appears exactly once, from the creation response** (UI-8,
 * DT-5). It is rendered from the rotate reply, held in a state variable
 * that dies with the tab, and never re-fetched, because no endpoint
 * returns it. There is no password input anywhere in this file: nothing
 * on this screen ever takes a secret *in*.
 *
 * **No detector-rule editor here.** §3 lists U-16 with this module, and
 * it is not built at B-1; the sidebar's dark states are honest about
 * what exists, and inventing a half-editor would be worse than the gap.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  api,
  type ApiError,
  type Hook,
  type HookList,
  type Job,
  type JobList,
  type RotatedSecret,
  type Run,
} from "./api";
import { Dark, duration, ServerSays, Spinner, StatusDot, Text } from "./ui";

const DOT: Record<string, string> = {
  succeeded: "green",
  running: "amber",
  queued: "amber",
  claimed: "amber",
  deferred: "amber",
  dead_lettered: "red",
  cancelled: "unknown",
};

function ago(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return String(iso);
  return `${duration((Date.now() - t) / 1000)} ago`;
}

function JobRow({ job, csrf, onChanged }: { job: Job; csrf: string | null; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  const reenqueue = async () => {
    setBusy(true);
    setError(null);
    const res = await api.post<{ job_id: string }>(
      `/v1/dashboard/ops/jobs/${encodeURIComponent(job.job_id)}/reenqueue`,
      {},
      csrf,
    );
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setCreated(res.data.job_id);
    onChanged();
  };

  return (
    <li className="job">
      <div className="job-head">
        <StatusDot status={DOT[job.state] ?? "unknown"} />
        <strong>
          <Text value={job.type} />
        </strong>
        <span className="muted">
          <Text value={job.system} /> · <Text value={job.state} /> · attempt{" "}
          <Text value={job.attempt} />/<Text value={job.max_attempts} /> · {ago(job.finished_at ?? job.created_at)}
        </span>
      </div>
      {job.error && (
        <div className="job-error">
          <code>
            <Text value={job.error.code} />
          </code>{" "}
          <Text value={job.error.message} />
          {job.error.retryable && <span className="muted"> · the connector called this retryable</span>}
        </div>
      )}
      {job.state === "dead_lettered" && (
        <div className="actions">
          <button onClick={reenqueue} disabled={busy || created !== null}>
            {busy ? <Spinner label="enqueueing…" /> : "Re-enqueue as me"}
          </button>
          <span className="muted small">
            Enqueues a new job with this one&apos;s payload, recorded under your identity. This row
            stays dead-lettered — it is the evidence of the failure, and nothing here rewrites it.
          </span>
        </div>
      )}
      {created && (
        <div className="saved">
          New job <code><Text value={created} /></code> queued. The dead job above is unchanged.
        </div>
      )}
      {error && <ServerSays error={error} />}
    </li>
  );
}

function Jobs({ csrf }: { csrf: string | null }) {
  const [list, setList] = useState<JobList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [state, setState] = useState("dead_lettered");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await api.get<JobList>(
      `/v1/dashboard/ops/jobs?limit=50${state === "all" ? "" : `&state=${encodeURIComponent(state)}`}`,
    );
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      setList(null);
      return;
    }
    setError(null);
    setList(res.data);
  }, [state]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ServerSays error={error} />;

  return (
    <section className="panel">
      <h3>Jobs</h3>
      {list && (
        <div className="tabs">
          {["dead_lettered", "queued", "running", "succeeded", "all"].map((s) => (
            <button key={s} className={state === s ? "active" : ""} onClick={() => setState(s)}>
              <Text value={s} />
              {list.counts[s] !== undefined && <span className="count-badge">{list.counts[s]}</span>}
            </button>
          ))}
        </div>
      )}
      {loading ? (
        <Spinner label="reading the queue…" />
      ) : !list || list.jobs.length === 0 ? (
        <Dark
          title={`No ${state === "all" ? "" : state.replace("_", "-")} jobs`}
          why="The queue holds none in this state right now. This is the queue's real contents, not a filtered-out view."
        />
      ) : (
        <ul className="job-list">
          {list.jobs.map((job) => (
            <JobRow key={job.job_id} job={job} csrf={csrf} onChanged={load} />
          ))}
        </ul>
      )}
    </section>
  );
}

function Runs() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void (async () => {
      const res = await api.get<{ runs: Run[] }>("/v1/dashboard/ops/runs?limit=15");
      if (!res.ok) setError(res.error);
      else setRuns(res.data.runs);
    })();
  }, []);

  if (error) return <ServerSays error={error} />;
  if (!runs) return <Spinner label="reading sync runs…" />;

  return (
    <section className="panel">
      <h3>Sync runs</h3>
      {runs.length === 0 ? (
        <Dark
          title="No sync run has ever completed"
          why="The drift pipeline has not run on this core. Nothing here is hidden — there is nothing recorded."
        />
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>Started</th>
              <th>Systems</th>
              <th>Outcome</th>
              <th>Contaminated</th>
              <th>PR</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.run_id}>
                <td>{ago(run.started_at)}</td>
                <td>
                  <Text value={run.systems.join(", ")} />
                </td>
                <td>
                  <Text value={run.outcome} />
                  {run.duration_ms !== null && (
                    <span className="muted small"> · {duration(run.duration_ms / 1000)}</span>
                  )}
                </td>
                <td>{run.contaminated_count > 0 ? run.contaminated_count : <span className="muted">—</span>}</td>
                <td>
                  {run.pr_url ? (
                    <a href={run.pr_url} target="_blank" rel="noreferrer noopener">
                      open
                    </a>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function HookRow({ hook, csrf }: { hook: Hook; csrf: string | null }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // The one place a secret exists in this client: a state variable, for
  // the life of this tab. Nothing writes it anywhere (D-103: no client
  // persistence — and the suite greps these sources for the storage APIs
  // by name).
  const [secret, setSecret] = useState<RotatedSecret | null>(null);

  const rotate = async () => {
    setBusy(true);
    setError(null);
    const res = await api.post<RotatedSecret>(
      `/v1/dashboard/ops/hooks/${encodeURIComponent(hook.system)}/rotate`,
      {},
      csrf,
    );
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    setSecret(res.data);
  };

  return (
    <li className="hook">
      <div className="hook-head">
        <strong>
          <Text value={hook.system} />
        </strong>
        <code>
          <Text value={hook.path} />
        </code>
        <span className="muted">
          {hook.configured ? (
            <>
              secret set{hook.rotated_at ? <> · rotated {ago(hook.rotated_at)}</> : null}
            </>
          ) : (
            "no secret — this hook would refuse every delivery"
          )}
        </span>
      </div>
      <div className="actions">
        <button onClick={rotate} disabled={busy}>
          {busy ? <Spinner label="rotating…" /> : hook.configured ? "Rotate secret" : "Create secret"}
        </button>
      </div>
      {error && <ServerSays error={error} />}
      {secret && (
        <div className="secret-once">
          <strong>Copy this now.</strong>
          <code className="secret-value">
            <Text value={secret.secret} />
          </code>
          <p>
            <Text value={secret.shown_once} />
          </p>
        </div>
      )}
    </li>
  );
}

function Hooks({ csrf }: { csrf: string | null }) {
  const [list, setList] = useState<HookList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    void (async () => {
      const res = await api.get<HookList>("/v1/dashboard/ops/hooks");
      if (!res.ok) setError(res.error);
      else setList(res.data);
    })();
  }, []);

  if (error) return <ServerSays error={error} />;
  if (!list) return <Spinner label="reading webhook configuration…" />;

  return (
    <section className="panel">
      <h3>Webhook secrets</h3>
      <p className="muted small">
        A secret is shown once, when it is created, and never again — the server keeps a hash of it
        and cannot give it back. Lose one and rotate for a new one; there is no endpoint on this
        product that reads a secret out.
      </p>
      {list.hooks.length === 0 ? (
        <Dark title="No connections" why="Webhook secrets belong to registered connections, and none exist yet." />
      ) : (
        <ul className="hook-list">
          {list.hooks.map((hook) => (
            <HookRow key={hook.system} hook={hook} csrf={csrf} />
          ))}
        </ul>
      )}
    </section>
  );
}

export function Ops({ csrf }: { csrf: string | null }) {
  return (
    <div className="ops-module">
      <Jobs csrf={csrf} />
      <Runs />
      <Hooks csrf={csrf} />
      <section className="panel">
        <h3>Detector rules</h3>
        {/* UI-10 rather than a half-built editor: the rules are live ops
            config and are edited outside this screen today. Saying so is
            more useful than a form that writes nothing. */}
        <Dark
          title="Not built yet"
          why="Detector-rule thresholds (U-16) and the regen-all trigger (U-17) are ops config the dashboard spec places in this module; neither has a screen at this checkpoint. The rules themselves are live — this view of them is not."
        />
      </section>
    </div>
  );
}
