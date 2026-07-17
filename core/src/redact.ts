/**
 * Defense-in-depth secret redaction over stored error detail (job spec
 * §7, security review #1 finding F3 / ruling D-66 point 2). The runner
 * scrubs its own exception messages and tracebacks before delivery
 * (connectors/sdk/redact.py); this is the core-side belt-and-suspenders
 * pass, applied to anything about to land in `jobs.error` or
 * `health_events.detail` — the two rows any bearer-token holder can read.
 *
 * It matches credential-shaped strings by pattern (the core never holds
 * resolved secret values — J-4 — so it cannot match by value): connection
 * URIs carrying userinfo (`postgres://user:pass@host/db`), libpq-style
 * keyword credentials (`password=…`), and bearer tokens. Matches collapse
 * to a fixed marker so the redaction is visible in triage, never the value.
 */

export const REDACTION_MARKER = "[redacted:credential]";

/** URI with embedded credentials: scheme://user:secret@host/… */
const CREDENTIAL_URI = /\b[a-z][a-z0-9+.\-]*:\/\/[^\s:/@]+:[^\s/@]+@\S+/gi;
/** libpq/connection-string keyword secrets: password=…, token=…, api_key=… */
const KEYWORD_SECRET =
  /\b(password|passwd|pwd|secret|token|api[_-]?key)\s*=\s*("[^"]*"|'[^']*'|\S+)/gi;
/** Bearer credentials that may ride in a copied header/detail. */
const BEARER = /\bBearer\s+[A-Za-z0-9._\-]+/gi;

/** Redact credential-shaped substrings in one string. No-op when none. */
export function redactString(value: string): string {
  return value
    .replace(CREDENTIAL_URI, REDACTION_MARKER)
    .replace(KEYWORD_SECRET, (_m, key: string) => `${key}=${REDACTION_MARKER}`)
    .replace(BEARER, REDACTION_MARKER);
}

/** Recursively redact every string in a JSON-ish value; structure preserved. */
export function redactDeep<T>(value: T): T {
  if (typeof value === "string") return redactString(value) as unknown as T;
  if (Array.isArray(value)) return value.map((v) => redactDeep(v)) as unknown as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) out[k] = redactDeep(v);
    return out as T;
  }
  return value;
}

/** Redact an error envelope's message + detail before storage (§7). */
export function redactError<T extends { message?: string; detail?: unknown }>(error: T): T {
  return {
    ...error,
    ...(typeof error.message === "string" ? { message: redactString(error.message) } : {}),
    ...(error.detail !== undefined ? { detail: redactDeep(error.detail) } : {}),
  };
}
