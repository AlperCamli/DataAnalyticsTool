/**
 * The small shared pieces, and the render-safety rule they carry.
 *
 * **Everything user-influenceable goes through `<Text>`** (UI-5, §6).
 * React escapes by default, so the danger is not `<b>` in a system name
 * — it is the day somebody reaches for React's raw-HTML escape hatch,
 * or a markdown renderer, to make an error message look nicer. Routing
 * every such string through one component makes that a visible edit to
 * a file whose whole purpose is to refuse it, rather than a one-line
 * convenience in a screen. The test asserts the escape hatch's name
 * appears nowhere in these sources, which is why this comment does not
 * write it out. The server neutralizes too (LED-R5, connections.ts);
 * this is the second layer the ruling asks for, not the only one.
 *
 * `<Dark>` is the honest-empty-state component (UI-10): it takes a
 * reason and prints it. There is no variant that renders sample data.
 */

import React from "react";

/** Render a server-supplied string inert. Never returns markup. */
export function Text({ value, fallback = "—" }: { value: unknown; fallback?: string }) {
  if (value === null || value === undefined || value === "") return <>{fallback}</>;
  // Coerced rather than trusted: a server that one day sends an object
  // where a string was expected must not become a render crash.
  return <>{String(value)}</>;
}

/** A stated dark state. The `why` is required — that is the point. */
export function Dark({ title, why, children }: { title: string; why: string; children?: React.ReactNode }) {
  return (
    <div className="dark-state">
      <h3>{title}</h3>
      <p>
        <Text value={why} />
      </p>
      {children}
    </div>
  );
}

/** The server's refusal, shown as the server's own words (DT-2). */
export function ServerSays({ error }: { error: { status: number; code: string; detail: string; fields?: string[] } }) {
  return (
    <div className={`server-says ${error.status === 403 ? "denied" : "error"}`}>
      <div className="server-says-head">
        <span className="code">
          <Text value={error.code} />
        </span>
        <span className="status">HTTP {error.status}</span>
      </div>
      <p>
        <Text value={error.detail} />
      </p>
      {error.fields && error.fields.length > 0 && (
        <ul>
          {error.fields.map((field, i) => (
            <li key={i}>
              <Text value={field} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function StatusDot({ status }: { status: string }) {
  return <span className={`dot dot-${status}`} aria-hidden="true" />;
}

/** Seconds → a duration a person reads without counting zeroes. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 172800) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export function Spinner({ label }: { label: string }) {
  return (
    <span className="spinner" role="status">
      <span className="spinner-mark" aria-hidden="true" />
      <Text value={label} />
    </span>
  );
}
