/**
 * The only way this client talks to anything (DT-8).
 *
 * Every call goes to a `/v1/...` endpoint on the same origin, carrying
 * the session cookie the browser already holds and, for writes, the
 * session's CSRF token. There is no second base URL, no direct database
 * anything, and no branch anywhere in this file that decides what the
 * caller may do — a 403 is a value returned from here, and the screens
 * render it as the server's words.
 *
 * Nothing is persisted: no browser storage of any kind, and no cookie
 * written by this code (D-103: no client persistence). The CSRF token
 * lives in a React state variable for the lifetime of the tab and dies
 * with it. The test greps these sources for the storage APIs by name,
 * which is why this comment does not spell them out.
 */

export interface ApiError {
  status: number;
  code: string;
  detail: string;
  fields?: string[];
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

async function request<T>(
  method: string,
  path: string,
  opts: { csrf?: string | null; body?: unknown } = {},
): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: {
        accept: "application/json",
        ...(opts.body !== undefined ? { "content-type": "application/json" } : {}),
        ...(opts.csrf ? { "x-cl-csrf": opts.csrf } : {}),
      },
      ...(opts.body !== undefined ? { body: JSON.stringify(opts.body) } : {}),
    });
  } catch (err) {
    return {
      ok: false,
      error: {
        status: 0,
        code: "unreachable",
        detail: `the core did not answer (${String(err)})`,
      },
    };
  }

  const text = await response.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }

  if (!response.ok) {
    const body = (parsed ?? {}) as { error?: string; detail?: string; fields?: string[] };
    return {
      ok: false,
      error: {
        status: response.status,
        code: body.error ?? `http_${response.status}`,
        detail: body.detail ?? text.slice(0, 400),
        ...(Array.isArray(body.fields) ? { fields: body.fields } : {}),
      },
    };
  }
  return { ok: true, data: (parsed ?? {}) as T };
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body: unknown, csrf: string | null) =>
    request<T>("POST", path, { body, csrf }),
  put: <T>(path: string, body: unknown, csrf: string | null) =>
    request<T>("PUT", path, { body, csrf }),
  del: <T>(path: string, csrf: string | null) => request<T>("DELETE", path, { csrf }),
};

// -- shapes, as the server sends them ---------------------------------------

export interface Session {
  subject: string;
  roles: string[];
  display?: string;
  csrf_token?: string;
  expires_at?: string;
}

export interface Module {
  id: string;
  title: string;
  path: string;
  built: boolean;
  description: string;
}

export interface ModuleMap {
  subject: string;
  display?: string;
  config_source: string;
  branding: string | null;
  modules: Module[];
}

export interface Health {
  status: "green" | "amber" | "red" | "unknown";
  reason: string;
  snapshot: {
    snapshot_id: string;
    captured_at: string;
    accepted_at: string;
    age_s: number;
    object_count: number;
    source_mode: string;
  } | null;
  policy: { threshold_s: number; trigger_mode: string } | null;
  freshness: string;
  last_job: {
    job_id: string;
    type: string;
    state: string;
    finished_at: string | null;
    error: { code?: string; message?: string } | null;
  } | null;
}

export interface Connection {
  system: string;
  connector: { name: string; version_constraint: string };
  config: Record<string, unknown>;
  credentials: { key: string | null; ref: string | null; required_for?: unknown[] }[];
  health: Health;
}

export interface ConnectionList {
  role_scope: "read" | "write";
  policy_readable: boolean;
  connections: Connection[];
}

// -- KB Health (B-1) ---------------------------------------------------------

export interface SourceRow {
  system: string;
  in_policy: boolean;
  last_snapshot_at: string | null;
  accepted_at: string | null;
  age_s: number | null;
  threshold_s: number | null;
  trigger_mode: string | null;
  schedule_interval_s: number | null;
  stale: boolean;
  warning_raised_at: string | null;
  render_lag: boolean;
}

export interface ContaminationRow {
  doc: string;
  title: string;
  object: string | null;
  source_object: string | null;
  change: string | null;
  detail: string | null;
  path: string[] | null;
  path_source: "recorded" | "declared" | "derived" | "self" | "unknown";
}

export interface KbHealth {
  kb: { ref: string; remote: string | null; render_failed: boolean };
  sync: {
    enabled: boolean;
    configured_systems: number;
    policy_readable: boolean;
    policy_error?: string;
    configured_but_disabled: boolean;
  };
  sources: SourceRow[];
  docs: { counts: Record<string, number>; total: number; scope_note: string };
  contamination: ContaminationRow[];
  drift_prs: {
    available: boolean;
    reason: string | null;
    prs: { number: number; title: string; url: string; branch: string }[];
  };
}

export interface Lineage {
  available: boolean;
  reason: string | null;
  kb_ref?: string;
  nodes: {
    id: string;
    node_kind: string | null;
    resolved: boolean;
    machine_doc: string | null;
    human_doc: string | null;
    status: string | null;
  }[];
  edges: { source: string; target: string; operation: string | null; trust: string | null }[];
}

// -- Ledger: triage, requests, inbox (B-1) -----------------------------------

export interface Issue {
  issue_id: string;
  kind: string;
  title: string;
  object_fqn?: string;
  system: string | null;
  status: string;
  occurrences: number;
  distinct_subjects: number;
  reopen_count: number;
  first_seen: string;
  last_seen: string;
  links: Record<string, unknown>;
  verdict: { by: string | null; at: string | null; reason: string | null } | null;
  batch_id: string | null;
  resolution: Record<string, unknown> | null;
  returned: { at: string; note: string | null } | null;
}

export interface IssueList {
  scope: { filed_by: string | null; role_scope: "self" | "all" };
  issues: Issue[];
  page: { limit: number; order: string; next_cursor: string | null };
}

export interface LedgerEvent {
  event_id: string;
  ts: string;
  detector_class: number;
  kind: string;
  system: string | null;
  object_fqn: string | null;
  subject?: string | null;
  profile: string | null;
  description: string | null;
  detail: Record<string, unknown>;
  routed_to: string;
}

export interface IssueDetail {
  issue: Issue;
  events: LedgerEvent[];
}

export interface Batch {
  batch_id: string;
  count: number;
  issues: Issue[];
  note: string;
}

export interface InboxItem {
  issue_id: string;
  kind: string;
  title: string;
  object_fqn?: string;
  status: string;
  unread: boolean;
  reopen_count: number;
  rejection: { by: string | null; at: string | null; reason: string | null } | null;
  resolution: { at: string | null; kind: string | null; pr_url: string | null } | null;
}

export interface Inbox {
  unread: number;
  items: InboxItem[];
}

// -- Publish + Ops (B-1) -----------------------------------------------------

export interface Delivery {
  artifact_id: string;
  target: string;
  subject: string | null;
  delivery: {
    revision: number;
    content_hash: string;
    workspace_id: string;
    dataset_id: string;
    delivered_at: string;
  };
  dangling: boolean;
  attestations: {
    revision: number;
    report_id: string;
    definition_hash: string;
    verified_at: string;
    attested_at: string;
  }[];
}

export interface DeliveryList {
  scope: { subject: string | null; role_scope: "self" | "all" };
  rows: Delivery[];
  page: { limit: number; order: string; next_cursor: string | null };
}

export interface Run {
  run_id: string;
  systems: string[];
  kb_ref: string | null;
  outcome: string;
  pr_url: string | null;
  classification_counts: Record<string, unknown>;
  contaminated_count: number;
  triggers: Record<string, unknown>[];
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
}

export interface Job {
  job_id: string;
  type: string;
  system: string;
  state: string;
  attempt: number;
  max_attempts: number;
  deferrals: number;
  error: { code: string; message: string; retryable: boolean } | null;
  triggers: Record<string, unknown>[];
  reenqueued_as: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Reenqueued {
  job_id: string;
  reenqueue_of: string;
  dead_job_unchanged: boolean;
  rebuilt_from_registration: boolean;
  references: { captured: string[]; current: string[]; changed: boolean; note?: string };
}

export interface JobList {
  counts: Record<string, number>;
  jobs: Job[];
}

export interface Hook {
  system: string;
  configured: boolean;
  created_at: string | null;
  rotated_at: string | null;
  path: string;
}

export interface HookList {
  role_scope: "read" | "write";
  hooks: Hook[];
}

export interface RotatedSecret {
  system: string;
  outcome: string;
  secret: string;
  shown_once: string;
  hook_path: string;
}

export interface TestCheck {
  capability: string;
  status: string;
  message?: string;
  facts?: Record<string, unknown>;
}

export interface TestResult {
  system: string;
  job_id: string;
  outcome: "pass" | "fail" | "pending";
  detail?: string;
  checks?: TestCheck[];
  unprobed?: string[];
  connector?: { name?: string; version?: string } | null;
  error?: { code: string; message: string; retryable: boolean };
  reauth?: {
    required: boolean;
    system: string;
    connector: string;
    message: string;
    credential_refs: string[];
    action: string;
  };
}
