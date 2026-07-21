/**
 * The execution gateway (MCP spec §6.7, capability §6, CP-6/M2).
 *
 * `execute_sql` is the one tool that reaches a customer's live data, so
 * this module's job is to be the place where every "did we check that?"
 * has exactly one answer:
 *
 * - **G4 / MCP-R5 token enforcement.** The validation token is verified
 *   in full before anything is enqueued: signature, statement bytes,
 *   subject, system, and snapshot currency. Any mismatch is
 *   `revalidate_required`. There is no silent re-validation path and no
 *   way to execute without a token — the verification library is the
 *   same one `validate_sql` issues with (vtoken.ts), so enforcement
 *   cannot drift from issuance.
 * - **F2 / D-71.1 visibility recheck.** The token's allow-set — the
 *   objects validation resolved the statement against — is re-checked
 *   against the caller's *current* visibility scopes. This is the check
 *   that catches a role losing access between validate and execute: the
 *   map lives in the KB, so a revocation moves `kb_ref` and leaves
 *   `snapshot_ref` untouched, and the §5 snapshot pin sails straight
 *   past it. A hidden member is `not_found`, worded as validation words
 *   it (M-4 — the caller learns nothing from having held a token).
 * - **G2 / MCP-R8 guardrail injection.** Guardrails are computed
 *   server-side from the profile and the system's conventions and are
 *   *written over* whatever the client sent. Client-supplied guardrails
 *   are not merged, not warned about, and not audited as authority —
 *   they are dropped.
 * - **Result relay.** The job is enqueued as interactive `execute` with
 *   `trigger.kind = gateway`, and the caller blocks on the JOB_DONE
 *   notification until the derived deadline.
 * - **Ledger linkage.** `schema_mismatch` at execute is the ledger's
 *   deterministic single-shot class-1 rule; guardrail terminations feed
 *   the `guardrail_pattern` window rule through the audit stream.
 *
 * What this module deliberately does *not* do: re-validate the
 * statement. A token means validation happened, against a pinned
 * snapshot, for this subject. If that pin no longer holds, the answer is
 * `revalidate_required` — not a quiet second opinion.
 */

import { createHash } from "node:crypto";
import pg from "pg";
import { canonicalJson } from "./audit.js";
import type { CoreConfig } from "./config.js";
import type { KbState } from "./kbread.js";
import { recordEvent } from "./ledger.js";
import type { Profile } from "./profiles.js";
import { awaitJobResult, enqueue, EnqueueError } from "./queue.js";
import { interactiveDeadlineS } from "./registry.js";
import { getSyncSystem } from "./triggers.js";
import { effectiveGuardrails } from "./valsql.js";
import { fqnVisible } from "./visibility.js";
import { verifyValidationToken } from "./vtoken.js";

export interface ExecuteIdentity {
  subject: string;
  roles: string[];
  display?: string | null;
}

export interface ExecuteOutcome {
  ok: boolean;
  /** Tool error code when !ok (MCP §7 taxonomy). */
  code?: string;
  message?: string;
  detail?: Record<string, unknown>;
  /** Capability §6 result envelope when ok. */
  result?: Record<string, unknown>;
  /** Audit/ledger facts, whatever the outcome. */
  meta: Record<string, unknown>;
  /** The exact statement text executed (audit stores it in full, §8). */
  statementText: string;
}

interface Notifier {
  waitFor(match: (payload: string | undefined) => boolean, ms: number): Promise<void>;
}

/**
 * The statement bytes the token is bound to. SQL binds the statement
 * verbatim; the API dialect binds the canonical JSON of
 * `{operation, body}` — identical to what validate_sql hashed, so a
 * re-ordered body cannot masquerade as a validated request.
 */
export function statementBinding(request: Record<string, unknown>): {
  sha256: string;
  text: string;
} {
  if (typeof request.statement === "string") {
    return {
      // The token binds the statement bytes exactly as §5 specifies —
      // `params` are deliberately outside the hash, so one validated
      // statement may be executed with different values. That is sound
      // (values cannot change which objects the statement touches, and
      // the driver binds them rather than interpolating), but it does
      // mean the statement alone is NOT a record of what ran — hence the
      // audit text below.
      sha256: createHash("sha256").update(request.statement).digest("hex"),
      text: auditText(request),
    };
  }
  const canonical = canonicalJson({ operation: request.operation, body: request.body });
  return { sha256: createHash("sha256").update(canonical).digest("hex"), text: canonical };
}

/**
 * What §8 stores for an execute: enough to reconstruct the execution,
 * not just its shape.
 *
 * A parameterized statement audited without its parameters records
 * `WHERE tenant_id = $1` and loses which tenant was read — the audit
 * would look complete while answering none of the questions an audit
 * exists to answer. Parameters are appended when present. They may
 * contain customer values, which is consistent with the statement text
 * itself already carrying literals for unparameterized queries.
 */
export function auditText(request: Record<string, unknown>): string {
  const statement = typeof request.statement === "string" ? request.statement : "";
  const params = request.params;
  if (!Array.isArray(params) || params.length === 0) return statement;
  return `${statement}\n-- params: ${canonicalJson(params)}`;
}

export interface ExecuteDeps {
  pool: pg.Pool;
  cfg: CoreConfig;
  notifier: Notifier;
  ws: KbState;
  identity: ExecuteIdentity;
  profile: Profile;
  /** The caller's visibility scopes, resolved this call (D-71.1). */
  scopes: string[];
  sessionId: string | null;
  auditId: string;
  intent?: string | null;
}

export async function executeRequest(
  deps: ExecuteDeps,
  args: { system: string; request: Record<string, unknown>; validationToken: string },
): Promise<ExecuteOutcome> {
  const { pool, cfg, ws, identity, profile } = deps;
  const system = args.system;
  const request = args.request ?? {};
  const binding = statementBinding(request);
  // Facts accumulated as the gateway makes its decisions, so that a
  // refusal at any stage still audits what had been decided by then —
  // in particular the guardrails, which MT-5 asserts are the profile's
  // and never the client's.
  const decided: Record<string, unknown> = { system };
  const fail = (
    code: string,
    message: string,
    extra: Record<string, unknown> = {},
  ): ExecuteOutcome => ({
    ok: false,
    code,
    message,
    ...(Object.keys(extra).length > 0 ? { detail: extra } : {}),
    meta: { ...decided, error: code, ...extra },
    statementText: binding.text,
  });

  const state = ws.systems.get(system);
  if (!state) {
    return fail("not_found", `no accepted snapshot for system ${system}`);
  }
  if (!args.validationToken) {
    // MCP-R5: there is no unvalidated execution path.
    return fail("revalidate_required", "execute_sql requires a validation_token from validate_sql");
  }

  // --- G4: full §5 verification, before anything else happens ---------------
  const currentSnapshotRef = `sha256:${state.canonicalBodySha256.replace(/^sha256:/, "")}`;
  const verified = await verifyValidationToken(
    pool,
    args.validationToken,
    {
      statementSha256: binding.sha256,
      system,
      subject: identity.subject,
      currentSnapshotRef,
      // D-71.1: the allow-set is checked against visibility as it is
      // *now*, not as it was when the token was minted.
      visible: (fqn) => fqnVisible(ws, deps.scopes, fqn),
    },
  );
  if (!verified.ok) {
    if (verified.code === "not_found") {
      // M-4, both halves. The caller gets validation's exact words for an
      // object that does not resolve and nothing else — note this does
      // NOT go through `fail()`, which copies its extras into the
      // caller-visible `detail` as well as into `meta`; the hidden FQNs
      // belong in the audit record only.
      const first = verified.hidden[0] ?? system;
      return {
        ok: false,
        code: "not_found",
        message: `object ${first} does not exist in the latest accepted snapshot`,
        meta: {
          ...decided,
          error: "not_found",
          stage: "visibility",
          filtered: true,
          hidden_objects: verified.hidden,
        },
        statementText: binding.text,
      };
    }
    return fail("revalidate_required", verified.reason, { stage: "token" });
  }

  // --- G2: guardrails are server-side, full stop (MCP-R8) -------------------
  // Anything the client put in `request.guardrails` is discarded here,
  // not merged: the envelope below is built only from the profile and
  // the system's conventions.
  const guardrails: Record<string, unknown> = {
    ...effectiveGuardrails(ws, system, profile),
    validated_against: verified.payload.snapshot_ref,
  };
  const clientSuppliedGuardrails = request.guardrails !== undefined;
  const cleanRequest = { ...request };
  delete cleanRequest.guardrails;
  decided.guardrails = guardrails;
  decided.client_guardrails_ignored = clientSuppliedGuardrails;
  decided.snapshot_ref = currentSnapshotRef;

  const registration = await getSyncSystem(pool, system);
  if (!registration) {
    return fail(
      "config_error",
      `system ${system} has no connection registered; execution needs a configured connector`,
    );
  }

  const payload = registration.payload as {
    config?: Record<string, unknown>;
    credentials?: { key?: unknown; required_for?: unknown }[];
  };
  // Credential scoping: an execute job gets ONLY the credentials the
  // connector declares for its query capability (manifest `required_for`,
  // capability §3). The registry entry is shared with snapshot jobs and
  // therefore also holds the *introspection* credential; handing that to
  // the execution path would widen what a compromised execute job can
  // reach, for no benefit — the executor reads `execute_dsn` and nothing
  // else. Fails closed: if nothing is marked for `query`, the job carries
  // no credentials and the executor says so, rather than quietly running
  // under the introspection role.
  const executionCredentials = (payload.credentials ?? []).filter((entry) => {
    const requiredFor = entry?.required_for;
    return Array.isArray(requiredFor) && requiredFor.includes("query");
  });
  if (executionCredentials.length === 0) {
    return fail(
      "config_error",
      `system ${system} has no credential marked for the query capability; ` +
        `mark the execution credential with required_for: ["query"] in the connection ` +
        `registration (see deploy/execution-role.sql for provisioning the role itself)`,
    );
  }
  const jobPayload = {
    config: { ...(payload.config ?? {}) },
    credentials: executionCredentials,
    identity: {
      subject: identity.subject,
      roles: identity.roles,
      ...(identity.display ? { display: identity.display } : {}),
      ...(deps.sessionId ? { session_id: deps.sessionId } : {}),
      ...(deps.intent ? { intent: deps.intent } : {}),
    },
    guardrails,
    request: cleanRequest,
  };

  const timeoutS = typeof guardrails.timeout_s === "number" ? guardrails.timeout_s : undefined;
  let jobId: string;
  try {
    ({ jobId } = await enqueue(pool, cfg, {
      type: "execute",
      system,
      connector: {
        name: registration.connector_name,
        version_constraint: registration.version_constraint,
      },
      payload: jobPayload,
      deadline_s: interactiveDeadlineS(timeoutS),
      trigger: { kind: "gateway", detail: { audit_id: deps.auditId } },
    }));
  } catch (err) {
    if (err instanceof EnqueueError) {
      return fail("config_error", `execute job rejected: ${err.problems.join("; ")}`);
    }
    throw err;
  }

  // --- await the result (§6.4 relay to the blocked producer) ---------------
  const awaitMs = interactiveDeadlineS(timeoutS) * 1000;
  const awaited = await awaitJobResult(pool, deps.notifier, jobId, awaitMs);

  const baseMeta = { ...decided, job_id: jobId };

  if (awaited.status === "timeout") {
    return {
      ok: false,
      code: "upstream_error",
      message:
        `execution did not complete within ${interactiveDeadlineS(timeoutS)}s ` +
        "(the job may still be running; it is bounded by the statement timeout)",
      meta: { ...baseMeta, error: "upstream_error", reason: "deadline" },
      statementText: binding.text,
    };
  }

  if (awaited.status === "failed") {
    const error = (awaited.error ?? {}) as {
      code?: string;
      message?: string;
      detail?: Record<string, unknown>;
    };
    const capabilityCode =
      typeof error.detail?.capability_code === "string" ? error.detail.capability_code : null;

    // Ledger linkage. `schema_mismatch` at execute is the ledger §5
    // deterministic single-shot rule; the guardrail codes feed the
    // `guardrail_pattern` window rule via the audit stream (result_meta).
    if (capabilityCode === "schema_mismatch") {
      await recordSchemaMismatch(deps, system, currentSnapshotRef, error);
    }

    return {
      ok: false,
      code: error.code === "guardrail" ? "guardrail" : "upstream_error",
      message: error.message ?? "execution failed",
      detail: {
        ...(capabilityCode ? { capability_code: capabilityCode } : {}),
        job_error: { code: error.code, message: error.message },
      },
      meta: {
        ...baseMeta,
        error: error.code ?? "upstream_error",
        ...(capabilityCode ? { guardrail_code: capabilityCode } : {}),
      },
      statementText: binding.text,
    };
  }

  const result = (awaited.result ?? {}) as Record<string, unknown>;
  return {
    ok: true,
    result,
    meta: {
      ...baseMeta,
      rows: typeof result.row_count === "number" ? result.row_count : null,
      truncated: result.truncated === true,
      duration_ms: typeof result.duration_ms === "number" ? result.duration_ms : null,
    },
    statementText: binding.text,
  };
}

/**
 * Ledger §5 `schema_mismatch_at_execute`: deterministic, single-shot.
 * The statement validated against a snapshot the live schema has since
 * moved past — a real doc/schema divergence, not a user error.
 */
async function recordSchemaMismatch(
  deps: ExecuteDeps,
  system: string,
  snapshotRef: string,
  error: { message?: string; detail?: Record<string, unknown> },
): Promise<void> {
  const rules = await deps.pool.query<{ enabled: boolean }>(
    `SELECT enabled FROM detector_rules WHERE rule = 'schema_mismatch_at_execute'`,
  );
  if (rules.rows[0] && !rules.rows[0].enabled) return;
  await recordEvent(deps.pool, {
    detectorClass: 1,
    kind: "doc_schema_mismatch",
    scope: `${system}:execute`,
    scopeLabel: `${system} (schema mismatch at execute)`,
    system,
    subject: deps.identity.subject,
    sessionId: deps.sessionId,
    profile: deps.profile.name,
    auditRef: deps.auditId,
    kbRef: deps.ws.headSha,
    snapshotRef: { [system]: snapshotRef },
    description: error.message ?? "statement referenced an object the live schema lacks",
    detail: { rule: "schema_mismatch_at_execute", capability_code: "schema_mismatch" },
  });
}
