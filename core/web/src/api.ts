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
