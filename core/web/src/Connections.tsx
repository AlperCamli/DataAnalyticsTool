/**
 * The Connections module (dashboard spec §3, checkpoint B-2) — the face
 * of A-3's API and, since D-63.8, the thing a vendor CLI has been
 * standing in for.
 *
 * Everything on this screen came from `/v1/dashboard/connections`, and
 * every act it offers is a call back to the same place (DT-8). It holds
 * no rule about who may do what: the add form and the test button are
 * rendered for everyone, and the server's 403 is what a reader without
 * ops rights sees when they use them. That is deliberate — a hidden
 * button teaches nobody why it is hidden, and a client that hides it is
 * a client that decided.
 *
 * The add form takes credential **references**, and says so in the form
 * itself rather than in documentation somebody will not read. There is
 * no password field on this screen, by design and by test.
 *
 * **A4-F1, closed here (D-114.6).** A-4's migration found that this
 * module rendered no config and offered no edit, so changing a
 * credential reference through the UI meant retyping the whole
 * registration from memory — which is why that migration had to be a
 * script instead of a screen. The card now shows the stored config and
 * the references, and Edit opens them prefilled. Two things keep that
 * inside UI-8: what is edited is a **reference**, never a value, and the
 * server refuses a payload carrying material regardless of what this
 * form sends. What comes back after a save is the store's read-back, not
 * the submitted form.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  api,
  type Connection,
  type ConnectionList,
  type ApiError,
  type TestResult,
} from "./api";
import { Dark, duration, ServerSays, Spinner, StatusDot, Text } from "./ui";

function HealthCell({ conn }: { conn: Connection }) {
  const h = conn.health;
  return (
    <div className="health">
      <div className="health-line">
        <StatusDot status={h.status} />
        <strong>
          <Text value={h.status} />
        </strong>
        <span className="muted">
          <Text value={h.reason} />
        </span>
      </div>
      <dl className="facts">
        <div>
          <dt>snapshot</dt>
          <dd>
            {h.snapshot ? (
              <>
                {duration(h.snapshot.age_s)} old · {h.snapshot.object_count} objects ·{" "}
                <Text value={h.snapshot.source_mode} />
              </>
            ) : (
              <span className="muted">none accepted yet</span>
            )}
          </dd>
        </div>
        <div>
          <dt>threshold</dt>
          <dd>
            {h.policy ? (
              <>
                {duration(h.policy.threshold_s)} · <Text value={h.policy.trigger_mode} />
              </>
            ) : (
              <span className="muted">not in sync-policy.yaml</span>
            )}
          </dd>
        </div>
        <div>
          <dt>last job</dt>
          <dd>
            {h.last_job ? (
              <>
                <Text value={h.last_job.type} /> · <Text value={h.last_job.state} />
                {h.last_job.error?.code ? (
                  <>
                    {" "}
                    · <span className="bad"><Text value={h.last_job.error.code} /></span>
                  </>
                ) : null}
              </>
            ) : (
              <span className="muted">no job has ever run for this system</span>
            )}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function TestPanel({ result }: { result: TestResult }) {
  return (
    <div className={`test-result test-${result.outcome}`}>
      <div className="test-head">
        <strong>
          {result.outcome === "pass" ? "Probe passed" : result.outcome === "fail" ? "Probe failed" : "No verdict yet"}
        </strong>
        <span className="muted">
          job <Text value={result.job_id} />
        </span>
      </div>

      {result.detail && (
        <p>
          <Text value={result.detail} />
        </p>
      )}

      {result.error && (
        <p className="bad">
          <Text value={result.error.code} />: <Text value={result.error.message} />
        </p>
      )}

      {/* The re-auth prompt (A-3 gate clause). Rendered from the
          server's `reauth` object — this client does not decide that an
          auth_error means re-auth, it is told. */}
      {result.reauth && (
        <div className="reauth">
          <h4>This connection needs its credential refreshed</h4>
          <p>
            <Text value={result.reauth.message} />
          </p>
          {result.reauth.credential_refs.length > 0 && (
            <ul className="refs">
              {result.reauth.credential_refs.map((ref, i) => (
                <li key={i}>
                  <code>
                    <Text value={ref} />
                  </code>
                </li>
              ))}
            </ul>
          )}
          <p>
            <Text value={result.reauth.action} />
          </p>
        </div>
      )}

      {result.checks && result.checks.length > 0 && (
        <ul className="checks">
          {result.checks.map((check, i) => (
            <li key={i} className={`check check-${check.status}`}>
              <span className="capability">
                <Text value={check.capability} />
              </span>
              <span className="verdict">
                <Text value={check.status} />
              </span>
              {check.message && (
                <span className="muted">
                  <Text value={check.message} />
                </span>
              )}
              {check.facts && (
                <span className="muted">
                  {Object.entries(check.facts)
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join(" · ")}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {result.unprobed && result.unprobed.length > 0 && (
        <p className="unprobed">
          Not exercised by this probe: <Text value={result.unprobed.join(", ")} />. A capability
          the probe could not run is not a capability that passed.
        </p>
      )}
    </div>
  );
}

const BLANK_FORM = {
  system: "",
  connector: "",
  version_constraint: "*",
  config: '{\n  "system": "",\n  "mode": "live"\n}',
  credentials:
    '[\n  { "key": "dsn", "ref": "vault://secret/contextlayer/connections/my_source#dsn", "required_for": ["live"] }\n]',
};

type FormState = typeof BLANK_FORM;

/** The stored row, as form text (A4-F1). Prefilled from what the API
 * rendered — so an edit that changes nothing round-trips to an identical
 * row, and nobody has to retype a reference from memory. */
function formFor(conn: Connection): FormState {
  return {
    system: conn.system,
    connector: conn.connector.name,
    version_constraint: conn.connector.version_constraint,
    config: JSON.stringify(conn.config ?? {}, null, 2),
    credentials: JSON.stringify(
      conn.credentials.map((c) => ({
        key: c.key,
        ref: c.ref,
        ...(c.required_for ? { required_for: c.required_for } : {}),
      })),
      null,
      2,
    ),
  };
}

/**
 * One form, two entries: registration and edit. They are the same act —
 * a connection is named by its system, so there is one address for it
 * and PUTting twice is changing it — and one form keeps them that way.
 */
function ConnectionForm({
  csrf,
  onDone,
  initial,
  mode,
  onCancel,
}: {
  csrf: string | null;
  onDone: () => void;
  initial?: FormState;
  mode: "register" | "edit";
  onCancel?: () => void;
}) {
  const [form, setForm] = useState<FormState>(initial ?? { ...BLANK_FORM });
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Connection | null>(null);

  const set = (key: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(null);
    let config: unknown;
    let credentials: unknown;
    try {
      config = JSON.parse(form.config || "{}");
    } catch (err) {
      setError({ status: 0, code: "config_not_json", detail: `config is not valid JSON: ${String(err)}` });
      return;
    }
    try {
      credentials = JSON.parse(form.credentials || "[]");
    } catch (err) {
      setError({ status: 0, code: "credentials_not_json", detail: `credentials is not valid JSON: ${String(err)}` });
      return;
    }
    setBusy(true);
    const result = await api.put<{ connection: Connection }>(
      `/v1/dashboard/connections/${encodeURIComponent(form.system)}`,
      {
        connector: { name: form.connector, version_constraint: form.version_constraint },
        payload: { config, credentials },
      },
      csrf,
    );
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    // What is shown back is the server's rendering of the stored row —
    // the read-back, not the form.
    setSaved(result.data.connection);
    if (mode === "register") setForm({ ...BLANK_FORM });
    onDone();
  };

  return (
    <form className="add-form" onSubmit={submit}>
      <h3>{mode === "edit" ? `Edit ${form.system}` : "Register a connection"}</h3>
      <p className="form-rule">
        Credential <strong>references only</strong> — <code>vault://mount/path#field</code>, or{" "}
        <code>env://NAME</code> where a pilot still runs on one. This product stores the reference;
        the value stays where the resolver reads it. A payload carrying an actual secret is refused
        by the server, and there is no field on this form to type one into. Changing a reference
        here changes <em>which</em> secret is used, never <em>what</em> it is.
      </p>

      <label>
        System
        <input
          value={form.system}
          onChange={set("system")}
          placeholder="supabase"
          required
          // The system names the row; editing it here would silently
          // register a second connection rather than change this one.
          readOnly={mode === "edit"}
        />
      </label>
      <label>
        Connector
        <input value={form.connector} onChange={set("connector")} placeholder="postgres" required />
      </label>
      <label>
        Version constraint
        <input value={form.version_constraint} onChange={set("version_constraint")} />
      </label>
      <label>
        Config (JSON — validated against the connector&apos;s own schema when a job runs)
        <textarea value={form.config} onChange={set("config")} rows={8} spellCheck={false} />
      </label>
      <label>
        Credential references (JSON array)
        <textarea value={form.credentials} onChange={set("credentials")} rows={6} spellCheck={false} />
      </label>

      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? <Spinner label="saving…" /> : mode === "edit" ? "Save changes" : "Register"}
        </button>
        {onCancel && (
          <button type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>

      {error && <ServerSays error={error} />}
      {saved && (
        <div className="saved">
          {mode === "edit" ? "Saved" : "Registered"} <strong><Text value={saved.system} /></strong> —
          this is the row the store returned when it was read back, not the form that was submitted.
        </div>
      )}
    </form>
  );
}

function ConnectionCard({
  conn,
  csrf,
  onChanged,
}: {
  conn: Connection;
  csrf: string | null;
  onChanged: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [editing, setEditing] = useState(false);

  const runTest = async () => {
    setTesting(true);
    setError(null);
    setResult(null);
    const res = await api.post<TestResult>(
      `/v1/dashboard/connections/${encodeURIComponent(conn.system)}/test`,
      {},
      csrf,
    );
    setTesting(false);
    if (!res.ok) setError(res.error);
    else setResult(res.data);
    onChanged();
  };

  const remove = async () => {
    setError(null);
    const res = await api.del(`/v1/dashboard/connections/${encodeURIComponent(conn.system)}`, csrf);
    if (!res.ok) setError(res.error);
    setConfirmRemove(false);
    onChanged();
  };

  return (
    <section className="conn-card">
      <header>
        <h3>
          <StatusDot status={conn.health.status} />
          <Text value={conn.system} />
        </h3>
        <span className="muted">
          <Text value={conn.connector.name} /> <Text value={conn.connector.version_constraint} />
        </span>
      </header>

      <HealthCell conn={conn} />

      <div className="refs-row">
        <span className="label">credential references</span>
        {conn.credentials.length === 0 ? (
          <span className="muted">none — this connector needs no credential</span>
        ) : (
          <ul className="refs">
            {conn.credentials.map((c, i) => (
              <li key={i}>
                <code>
                  <Text value={c.ref} />
                </code>{" "}
                <span className="muted">
                  as <Text value={c.key} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* A4-F1: the config, rendered. It was absent before, which is why
          changing a reference meant reconstructing the whole
          registration from memory. These are settings, not secrets —
          the values live where the references above point. */}
      <div className="config-row">
        <span className="label">config</span>
        {Object.keys(conn.config ?? {}).length === 0 ? (
          <span className="muted">none — this connector is configured entirely by its credential</span>
        ) : (
          <pre className="config">
            <Text value={JSON.stringify(conn.config, null, 2)} />
          </pre>
        )}
      </div>

      <div className="actions">
        <button onClick={runTest} disabled={testing}>
          {testing ? <Spinner label="probing…" /> : "Test connection"}
        </button>
        <button onClick={() => setEditing((v) => !v)}>{editing ? "Close editor" : "Edit…"}</button>
        {confirmRemove ? (
          <>
            <button className="danger" onClick={remove}>
              Remove {conn.system}
            </button>
            <button onClick={() => setConfirmRemove(false)}>Cancel</button>
          </>
        ) : (
          <button onClick={() => setConfirmRemove(true)}>Remove…</button>
        )}
      </div>

      {editing && (
        <ConnectionForm
          csrf={csrf}
          mode="edit"
          initial={formFor(conn)}
          onCancel={() => setEditing(false)}
          onDone={onChanged}
        />
      )}

      {error && <ServerSays error={error} />}
      {result && <TestPanel result={result} />}
    </section>
  );
}

export function Connections({ csrf }: { csrf: string | null }) {
  const [list, setList] = useState<ConnectionList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const res = await api.get<ConnectionList>("/v1/dashboard/connections");
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

  if (loading) return <Spinner label="loading connections…" />;
  // The denied case is the server's answer, printed (DT-2/UI-1).
  if (error) return <ServerSays error={error} />;
  if (!list) return null;

  return (
    <div className="connections">
      {!list.policy_readable && (
        <div className="notice">
          <strong>sync-policy.yaml could not be read from the knowledge base.</strong> Freshness is
          reported as <em>unknown</em> below rather than green — nothing here states how old these
          snapshots may get.
        </div>
      )}

      {list.connections.length === 0 ? (
        <Dark
          title="No connections registered"
          why="This estate has no sources wired yet. Register one below; nothing on this screen is a placeholder."
        />
      ) : (
        list.connections.map((conn) => (
          <ConnectionCard key={conn.system} conn={conn} csrf={csrf} onChanged={load} />
        ))
      )}

      <ConnectionForm csrf={csrf} mode="register" onDone={load} />
    </div>
  );
}
