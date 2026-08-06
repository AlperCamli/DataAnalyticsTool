/**
 * The filer's inbox — F-10's reply path, with the mechanism UI-D fixed
 * (D-103.2): a dashboard badge on the filer's next session, carrying
 * rejection reasons and batch-merge resolutions alike.
 *
 * The count in the sidebar is a **server** number (`unread` from
 * `/v1/dashboard/inbox`), and "seen" is server state: acknowledging is a
 * write under the caller's own identity, so the badge does not come back
 * on the next reload, in a second tab, or on another machine. The client
 * persists nothing and could not — that is D-103.1's constraint, and it
 * is why the ack is an endpoint rather than a flag in the browser.
 *
 * The scope is the session's subject, decided server-side. There is no
 * subject on any call this file makes.
 *
 * **In-session surfacing is not this.** UI-D names a `report_freshness`-
 * style line inside the user's own session as a skill-side candidate,
 * and it is **unbuilt**. This badge is the shipped half.
 */

import React, { useState } from "react";
import { api, type ApiError, type Inbox as InboxData, type InboxItem } from "./api";
import { Dark, ServerSays, Spinner, Text } from "./ui";

function when(iso: string | null): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

function Item({ item }: { item: InboxItem }) {
  return (
    <li className={`inbox-item${item.unread ? " unread" : ""}`}>
      <div className="inbox-head">
        {item.unread && <span className="unread-dot" aria-label="unread" />}
        <strong>
          <Text value={item.title} />
        </strong>
      </div>

      {item.rejection && (
        <div className="inbox-body rejected">
          <div className="label">
            Declined by <Text value={item.rejection.by} /> {when(item.rejection.at)}
          </div>
          <blockquote>
            <Text value={item.rejection.reason} fallback="(no reason recorded)" />
          </blockquote>
          <p className="muted small">
            The request is on the record, not deleted. If this comes up again — for you or for
            somebody else — filing it again reopens it with the count of how many people have now
            asked.
          </p>
        </div>
      )}

      {item.resolution && (
        <div className="inbox-body resolved">
          <div className="label">Answered {when(item.resolution.at)}</div>
          {item.resolution.pr_url ? (
            <p>
              A pull request was reviewed and merged:{" "}
              <a href={item.resolution.pr_url} target="_blank" rel="noreferrer noopener">
                read the diff that landed
              </a>
              . The knowledge base now says something it did not before — the diff is what a person
              actually approved, so it is the thing worth reading, not this line.
            </p>
          ) : (
            <p>This was marked resolved. No pull request is recorded against it.</p>
          )}
        </div>
      )}

      {item.reopen_count > 0 && (
        <p className="muted small">
          Reopened <Text value={item.reopen_count} /> time(s) before this.
        </p>
      )}
    </li>
  );
}

export function Inbox({
  data,
  csrf,
  onAcked,
}: {
  data: InboxData | null;
  csrf: string | null;
  onAcked: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  if (!data) return <Spinner label="reading your inbox…" />;

  const unread = data.items.filter((i) => i.unread);

  const ack = async () => {
    setBusy(true);
    setError(null);
    const res = await api.post(
      "/v1/dashboard/inbox/ack",
      { issue_ids: unread.map((i) => i.issue_id) },
      csrf,
    );
    setBusy(false);
    if (!res.ok) {
      setError(res.error);
      return;
    }
    onAcked();
  };

  return (
    <div className="inbox">
      {data.items.length === 0 ? (
        <Dark
          title="Nothing has come back yet"
          why="Nothing you filed has reached a verdict or been answered by a merged pull request. When one does, it appears here and the sidebar carries a count."
        />
      ) : (
        <>
          <div className="inbox-bar">
            <span>
              <Text value={unread.length} /> new · <Text value={data.items.length} /> in total
            </span>
            {unread.length > 0 && (
              <button onClick={ack} disabled={busy}>
                {busy ? <Spinner label="marking…" /> : "Mark all as read"}
              </button>
            )}
          </div>
          {error && <ServerSays error={error} />}
          <ul className="inbox-list">
            {data.items.map((item) => (
              <Item key={item.issue_id} item={item} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
