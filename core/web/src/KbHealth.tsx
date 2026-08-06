/**
 * KB Health (dashboard spec §3, checkpoint B-1) — R2's home screen.
 *
 * Everything here came from `/v1/dashboard/kb-health`, one governed read.
 * The screen computes nothing about permissions and nothing about
 * staleness: `stale` is a server verdict, the doc counts are the server's
 * counts over the docs *this* caller can see, and the contamination
 * paths were walked server-side against the lineage graph.
 *
 * Two absences are deliberate and are asserted by test. There is **no
 * merge affordance** anywhere in this file — the drift-PR queue offers a
 * link out to the git provider and nothing else (§7.3, UI-6), and a
 * merge button is not the risk, a *code path* is. And there is **no
 * placeholder number**: a section with no data renders `<Dark>` with the
 * reason, never a zero dressed up as a measurement (UI-10).
 */

import React, { useCallback, useEffect, useState } from "react";
import { api, type ApiError, type ContaminationRow, type KbHealth as Health, type Lineage, type SourceRow } from "./api";
import { Dark, duration, ServerSays, Spinner, StatusDot, Text } from "./ui";

/** The freshness verdict as a word, because colour alone is not a state. */
function sourceStatus(row: SourceRow): { dot: string; word: string; why: string } {
  if (!row.in_policy) {
    return {
      dot: "unknown",
      word: "not a sync source",
      why: "absent from sync-policy.yaml, so no snapshot is expected and freshness is not its verdict",
    };
  }
  if (row.age_s === null) {
    return { dot: "red", word: "never synced", why: "the policy lists this system and no snapshot has ever been accepted for it" };
  }
  if (row.stale) {
    return {
      dot: "red",
      word: "stale",
      why: `last snapshot ${duration(row.age_s)} old, past its ${duration(row.threshold_s)} threshold`,
    };
  }
  return {
    dot: "green",
    word: "fresh",
    why: `last snapshot ${duration(row.age_s)} old, inside its ${duration(row.threshold_s)} threshold`,
  };
}

function FreshnessMap({ health }: { health: Health }) {
  const { sync, sources } = health;
  return (
    <section className="panel">
      <h3>Freshness</h3>

      {/* DT-9 / SO-F: the two-silent-days shape. The estate is configured
          to sync and this core's sync engine is off, so no trigger will
          ever fire and every source below will age in silence. */}
      {sync.configured_but_disabled && (
        <div className="notice warn">
          <strong>Sync is configured but disabled on this core.</strong>{" "}
          <code>sync-policy.yaml</code> configures <Text value={sync.configured_systems} /> system(s)
          with thresholds and triggers, and this core&apos;s sync engine is off — so no trigger will
          fire, no snapshot will arrive, and every threshold below will be crossed without anything
          reporting a failure. Nothing here is broken; nothing here is running either.
        </div>
      )}

      {!sync.policy_readable && (
        <div className="notice warn">
          <strong>sync-policy.yaml could not be read at HEAD.</strong>{" "}
          <Text value={sync.policy_error ?? "No thresholds are known, so no source below can be called fresh or stale."} />
        </div>
      )}

      {health.kb.render_failed && (
        <div className="notice warn">
          <strong>The machine docs served are HEAD&apos;s, not the latest snapshot&apos;s.</strong> The
          re-render against the newest accepted snapshots failed, so facts may lag what the sources
          actually hold.
        </div>
      )}

      {sources.length === 0 ? (
        <Dark
          title="No sources"
          why="No system has an accepted snapshot and sync-policy.yaml names none. Register a connection first."
        />
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>System</th>
              <th>State</th>
              <th>Last snapshot</th>
              <th>Threshold</th>
              <th>Trigger</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((row) => {
              const status = sourceStatus(row);
              return (
                <tr key={row.system}>
                  <td>
                    <strong>
                      <Text value={row.system} />
                    </strong>
                    {row.render_lag && (
                      <div className="muted small">
                        render lag: a newer snapshot is accepted than the KB was rendered against
                      </div>
                    )}
                  </td>
                  <td>
                    <StatusDot status={status.dot} />
                    <Text value={status.word} />
                    <div className="muted small">
                      <Text value={status.why} />
                    </div>
                  </td>
                  <td>{row.age_s === null ? <span className="muted">never</span> : `${duration(row.age_s)} ago`}</td>
                  <td>{row.threshold_s === null ? <span className="muted">—</span> : duration(row.threshold_s)}</td>
                  <td>
                    <Text value={row.trigger_mode} />
                    {row.schedule_interval_s !== null && (
                      <span className="muted"> · every {duration(row.schedule_interval_s)}</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}

/** The KB's own trust ladder, counted. Order is the ladder's, not
 * alphabetical: a reader should see `contaminated` next to `verified`. */
const STATUS_ORDER = ["verified", "draft", "stale", "contaminated"];

function DocStatus({ health }: { health: Health }) {
  const { counts, total, scope_note } = health.docs;
  const known = STATUS_ORDER.filter((s) => counts[s] !== undefined);
  const extra = Object.keys(counts).filter((s) => !STATUS_ORDER.includes(s)).sort();

  if (total === 0) {
    return (
      <section className="panel">
        <h3>Document status</h3>
        <Dark
          title="No human-owned docs are visible to you"
          why="Either this knowledge base has none yet, or your roles' visibility map covers none of them. No number here would mean anything."
        />
      </section>
    );
  }

  return (
    <section className="panel">
      <h3>Document status</h3>
      <div className="tiles">
        {[...known, ...extra].map((status) => (
          <div key={status} className={`tile tile-${status}`}>
            <span className="tile-n">
              <Text value={counts[status]} />
            </span>
            <span className="tile-label">
              <Text value={status} />
            </span>
          </div>
        ))}
      </div>
      <p className="muted small">
        <Text value={scope_note} /> · <Text value={total} /> in total · KB{" "}
        <code>
          <Text value={health.kb.ref.slice(0, 10)} />
        </code>
      </p>
    </section>
  );
}

/** How the contamination reached a doc, said in words the grade earns. */
function pathNote(row: ContaminationRow): string {
  switch (row.path_source) {
    case "recorded":
      return "path recorded by the sync scan that marked this doc";
    case "declared":
      return "direct dependency — this doc declares the changed object in depends_on";
    case "derived":
      return "walked from lineage/graph.json: the changed object reaches this doc's object through these hops";
    case "self":
      return "the changed object is this doc's own subject";
    default:
      return "no path is known — this doc did not declare the changed object and the lineage graph does not connect them, which is itself worth a look";
  }
}

function Contamination({ rows }: { rows: ContaminationRow[] }) {
  if (rows.length === 0) {
    return (
      <section className="panel">
        <h3>Contamination</h3>
        <Dark
          title="No contaminated docs"
          why="No human doc at KB HEAD carries status: contaminated. This is the estate's real state, not an empty view."
        />
      </section>
    );
  }
  return (
    <section className="panel">
      <h3>
        Contamination <span className="count-badge">{rows.length}</span>
      </h3>
      <p className="muted small">
        A doc is contaminated when a breaking change landed under something it relies on. Repair is a
        pull request — read the doc, fix the claim, and let a human merge the diff. Nothing on this
        screen edits a doc.
      </p>
      <ul className="issue-list">
        {rows.map((row) => (
          <li key={row.doc} className="issue">
            <div className="issue-head">
              <code>
                <Text value={row.doc} />
              </code>
            </div>
            <div className="muted">
              <Text value={row.title} />
            </div>
            <div className="contam-why">
              <span className="label">changed</span>
              <code>
                <Text value={row.source_object} />
              </code>
              <span className="muted">
                <Text value={row.change} />
                {row.detail ? (
                  <>
                    {" · "}
                    <Text value={row.detail} />
                  </>
                ) : null}
              </span>
            </div>
            <div className="contam-path">
              <span className="label">path</span>
              {row.path === null ? (
                <span className="muted">unknown</span>
              ) : (
                <span className="hops">
                  {row.path.map((hop, i) => (
                    <React.Fragment key={i}>
                      {i > 0 && <span className="arrow">→</span>}
                      <code>
                        <Text value={hop} />
                      </code>
                    </React.Fragment>
                  ))}
                </span>
              )}
              <span className="muted small">
                <Text value={pathNote(row)} />
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The drift-PR queue: routing, never merging (§7.3).
 *
 * Every row is a link out. The provider's own auth is what opens it, and
 * this page carries no credential into it (§6). There is no merge control
 * here and no API call in this component that could become one.
 */
function DriftPrs({ queue }: { queue: Health["drift_prs"] }) {
  return (
    <section className="panel">
      <h3>Drift pull requests</h3>
      {!queue.available ? (
        <Dark title="This queue is unknown, not empty" why={queue.reason ?? "the provider did not answer"} />
      ) : queue.prs.length === 0 ? (
        <Dark
          title="No open drift PRs"
          why="The sync engine has no unmerged snapshot drift waiting for review right now."
        />
      ) : (
        <>
          <ul className="pr-list">
            {queue.prs.map((pr) => (
              <li key={pr.number}>
                <a href={pr.url} target="_blank" rel="noreferrer noopener">
                  #<Text value={pr.number} /> <Text value={pr.title} />
                </a>
                <span className="muted">
                  {" "}
                  <code>
                    <Text value={pr.branch} />
                  </code>
                </span>
              </li>
            ))}
          </ul>
          <p className="muted small">
            These open in your git provider, under your own sign-in there. The product never merges
            — reviewing the diff and merging it is the act that changes the knowledge base, and it
            stays a human&apos;s (sync spec SO-B, dashboard spec §7.3).
          </p>
        </>
      )}
    </section>
  );
}

/**
 * The lineage explorer's read view (U-15).
 *
 * Read view means read: it shows what depends on what, with the trust
 * tier each edge was derived at, and offers nothing that edits a graph
 * the generator owns. Loaded on demand — a graph is the largest payload
 * on this screen and most visits to KB Health do not want it.
 */
function LineageExplorer() {
  const [graph, setGraph] = useState<Lineage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [focus, setFocus] = useState("");

  const load = async () => {
    setOpen(true);
    if (graph || loading) return;
    setLoading(true);
    const res = await api.get<Lineage>("/v1/dashboard/lineage");
    setLoading(false);
    if (!res.ok) setError(res.error);
    else setGraph(res.data);
  };

  if (!open) {
    return (
      <section className="panel">
        <h3>Lineage</h3>
        <button onClick={load}>Show the lineage graph</button>
      </section>
    );
  }

  return (
    <section className="panel">
      <h3>Lineage</h3>
      {loading && <Spinner label="reading the graph…" />}
      {error && <ServerSays error={error} />}
      {graph && !graph.available && <Dark title="No lineage graph" why={graph.reason ?? "none at HEAD"} />}
      {graph && graph.available && (
        <>
          <label className="filter">
            Filter by name
            <input
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              placeholder="supabase.public.users"
              spellCheck={false}
            />
          </label>
          <p className="muted small">
            <Text value={graph.nodes.length} /> nodes · <Text value={graph.edges.length} /> edges ·
            nodes your roles cannot see are absent, and so is every edge that touched them.
          </p>
          <ul className="edge-list">
            {graph.edges
              .filter((e) => !focus || e.source.includes(focus) || e.target.includes(focus))
              .slice(0, 200)
              .map((edge, i) => (
                <li key={i}>
                  <code>
                    <Text value={edge.source} />
                  </code>
                  <span className="arrow">→</span>
                  <code>
                    <Text value={edge.target} />
                  </code>
                  <span className="muted small">
                    <Text value={edge.operation} /> · trust <Text value={edge.trust} />
                  </span>
                </li>
              ))}
          </ul>
          {graph.edges.filter((e) => !focus || e.source.includes(focus) || e.target.includes(focus)).length >
            200 && (
            <p className="muted small">
              Showing the first 200 of the matching edges — narrow the filter to see the rest. This
              is a display cap, not a filter the server applied.
            </p>
          )}
        </>
      )}
    </section>
  );
}

export function KbHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const res = await api.get<Health>("/v1/dashboard/kb-health");
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      setHealth(null);
      return;
    }
    setError(null);
    setHealth(res.data);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner label="reading the knowledge base…" />;
  if (error) return <ServerSays error={error} />;
  if (!health) return null;

  return (
    <div className="kb-health">
      <FreshnessMap health={health} />
      <DocStatus health={health} />
      <Contamination rows={health.contamination} />
      <DriftPrs queue={health.drift_prs} />
      <LineageExplorer />
    </div>
  );
}
