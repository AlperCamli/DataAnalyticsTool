/**
 * validate_sql (MCP spec §6.6, M-1): one tool, dialect-switched by the
 * system's class. SQL statements go to the Python sqlval stage CLI
 * (sqlglot — parser-based refusal set, MCP-R6/R7; the C1/C2 pattern,
 * never TypeScript SQL parsing); API requests validate against the
 * documented dimension/metric surface from the latest snapshot (MT-8).
 * A `pass` issues the signed validation token (§5, MCP-R5) bound to
 * the exact statement bytes, subject, system, and current snapshot.
 * Guardrails in the response are echoed from server-side profile
 * limits merged over the conventions guardrail block (MCP-R8) — client
 * arguments never contribute.
 *
 * **Visibility governs this surface** (D-71.1 / security review #2 F2,
 * spec §6.6 amendment). Resolution runs against the objects the caller
 * can see, not the whole snapshot: the visible surface is the *input*
 * to resolution, never a filter over its output. That ordering is the
 * whole non-disclosure argument — a hidden object and a nonexistent one
 * produce the same finding from the same code path, so there is no
 * second message to keep in sync and no branch that could leak which
 * case it was. The true reason is recovered afterwards, server-side
 * only, for the audit record (M-4's admin half).
 */

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import type { CoreConfig } from "./config.js";
import { canonicalJson } from "./audit.js";
import type { KbState, SnapshotObject } from "./kbread.js";
import type { Profile } from "./profiles.js";
import { fqnVisible } from "./visibility.js";
import { issueValidationToken } from "./vtoken.js";

export interface Finding {
  severity: string;
  code: string;
  ref: string | null;
  message: string;
}

export interface ValidateOutcome {
  verdict: "pass" | "fail";
  findings: Finding[];
  guardrails: Record<string, unknown>;
  statementSha256: string | null;
  citedObjects: string[];
  /**
   * FQNs the request referenced that exist in the snapshot but are
   * hidden from this caller (§6.6 amendment). Never surfaced to the
   * caller — the audit record's true reason, and nothing else.
   */
  hiddenObjects: string[];
  validationToken?: { token: string; expiresAt: string };
  error?: { code: string; message: string };
}

export class SqlValidatorUnavailable extends Error {}

function runSqlval(
  pythonCmd: string[],
  requestFile: string,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const child = spawn(pythonCmd[0]!, [...pythonCmd.slice(1), "-m", "sqlval", requestFile], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d: Buffer) => (stdout += d.toString()));
    child.stderr.on("data", (d: Buffer) => (stderr += d.toString()));
    child.on("error", (err) => reject(new SqlValidatorUnavailable(`cannot spawn sqlval: ${err.message}`)));
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

/** Server-side guardrails: profile limits over the conventions row (MCP-R8). */
export function effectiveGuardrails(
  ws: KbState,
  system: string,
  profile: Profile,
): Record<string, unknown> {
  const conventions = ws.guardrails[system] ?? {};
  return {
    statement_class: "select-only",
    ...(typeof conventions.timeout_s === "number" ? { timeout_s: conventions.timeout_s } : {}),
    ...(typeof conventions.row_cap === "number" ? { row_cap: conventions.row_cap } : {}),
    ...(profile.limits.timeout_s !== undefined ? { timeout_s: profile.limits.timeout_s } : {}),
    ...(profile.limits.row_cap !== undefined ? { row_cap: profile.limits.row_cap } : {}),
  };
}

/**
 * The caller's slice of a system's snapshot (§6.6 amendment): the
 * objects they may resolve against, plus the lookup the server needs
 * afterwards to tell "hidden" from "absent" for the audit.
 */
interface VisibleSurface {
  objects: SnapshotObject[];
  /** lower(fqn) → canonical fqn, over the *whole* snapshot. */
  allByLower: Map<string, string>;
  /** `kind:lower(name)` → canonical fqn, over the whole snapshot (API dialect). */
  allByKindName: Map<string, string>;
  /** Canonical FQNs that exist but are hidden from this caller. */
  hidden: Set<string>;
}

function visibleSurface(ws: KbState, scopes: string[], system: string): VisibleSurface {
  const state = ws.systems.get(system)!;
  const objects: SnapshotObject[] = [];
  const allByLower = new Map<string, string>();
  const allByKindName = new Map<string, string>();
  const hidden = new Set<string>();
  for (const obj of state.objects.values()) {
    allByLower.set(obj.fqn.toLowerCase(), obj.fqn);
    allByKindName.set(`${obj.kind}:${obj.name.toLowerCase()}`, obj.fqn);
    if (fqnVisible(ws, scopes, obj.fqn)) objects.push(obj);
    else hidden.add(obj.fqn);
  }
  return { objects, allByLower, allByKindName, hidden };
}

/**
 * The true reason, recovered after the fact: which of the refusals
 * were hidden objects rather than absent ones. Matching is
 * case-insensitive because the finding's `ref` carries the identifier
 * as the caller wrote it, while the snapshot carries it as the source
 * spells it.
 */
function hiddenAmong(surface: VisibleSurface, refs: (string | null)[]): string[] {
  const found: string[] = [];
  for (const ref of refs) {
    if (!ref) continue;
    const canonical = surface.allByLower.get(ref.toLowerCase());
    if (canonical && surface.hidden.has(canonical) && !found.includes(canonical)) {
      found.push(canonical);
    }
  }
  return found;
}

export async function validateRequest(
  cfg: CoreConfig,
  pool: pg.Pool,
  ws: KbState,
  identity: { subject: string },
  profile: Profile,
  scopes: string[],
  args: { system: string; request: Record<string, unknown> },
): Promise<ValidateOutcome> {
  const system = args.system;
  const state = ws.systems.get(system);
  const guardrails = effectiveGuardrails(ws, system, profile);
  const base: ValidateOutcome = {
    verdict: "fail",
    findings: [],
    guardrails,
    statementSha256: null,
    citedObjects: [],
    hiddenObjects: [],
  };
  if (!state) {
    return { ...base, error: { code: "not_found", message: `no accepted snapshot for system ${system}` } };
  }
  const request = args.request ?? {};
  const dialect = request.dialect;
  const expectedDialect = state.systemClass === "sql" ? "sql" : "api";
  if (dialect !== expectedDialect) {
    return {
      ...base,
      error: {
        code: "invalid_argument",
        message: `system ${system} takes dialect ${expectedDialect}, got ${String(dialect)}`,
      },
    };
  }

  // §6.6 amendment: the caller's slice of the snapshot is what
  // resolution sees. Everything below resolves against `surface`.
  const surface = visibleSurface(ws, scopes, system);

  let outcome: ValidateOutcome;
  if (dialect === "sql") {
    outcome = await validateSqlDialect(cfg, ws, system, surface, request, base);
  } else {
    outcome = validateApiDialect(ws, system, surface, request, base);
  }

  if (outcome.verdict === "pass" && outcome.statementSha256) {
    outcome.validationToken = await issueValidationToken(
      pool,
      {
        statementSha256: outcome.statementSha256,
        system,
        snapshotRef: `sha256:${state.canonicalBodySha256.replace(/^sha256:/, "")}`,
        subject: identity.subject,
        profile: profile.name,
        // The allow-set §5 carries to execute. A `pass` can only cite
        // visible objects, so this is exactly what was authorized.
        objects: outcome.citedObjects,
      },
      cfg.mcp.vtokenTtlS,
    );
  }
  return outcome;
}

async function validateSqlDialect(
  cfg: CoreConfig,
  ws: KbState,
  system: string,
  surface: VisibleSurface,
  request: Record<string, unknown>,
  base: ValidateOutcome,
): Promise<ValidateOutcome> {
  const statement = request.statement;
  if (typeof statement !== "string" || !statement.trim()) {
    return { ...base, error: { code: "invalid_argument", message: "request.statement (string) required" } };
  }
  const conventions = ws.guardrails[system] ?? {};
  // Hidden objects are not in this list, so sqlval cannot resolve them
  // and reports them with the same `unknown_object` finding it gives a
  // table that was never there — including for column resolution, which
  // only ever sees the columns of objects that survived this filter.
  const objects = surface.objects.map((obj) => ({
    schema: obj.schema,
    name: obj.name,
    kind: obj.kind,
    columns: obj.columns.map((c) => c.name),
  }));
  const payload = {
    statement,
    engine: typeof conventions.dialect === "string" && conventions.dialect !== "api" ? conventions.dialect : "postgres",
    system,
    default_schema: "public",
    objects,
    denied_functions: Array.isArray(conventions.denied_functions) ? conventions.denied_functions : [],
  };
  const dir = await mkdtemp(path.join(tmpdir(), "cl-sqlval-"));
  try {
    const requestFile = path.join(dir, "request.json");
    await writeFile(requestFile, JSON.stringify(payload));
    const { code, stdout, stderr } = await runSqlval(cfg.sync.pythonCmd, requestFile);
    if (code !== 0 && code !== 1) {
      throw new SqlValidatorUnavailable(`sqlval exited ${code}: ${stderr.slice(0, 2000)}`);
    }
    let verdict: {
      verdict: "pass" | "fail";
      findings: Finding[];
      statement_sha256?: string;
      referenced_objects?: string[];
    };
    try {
      verdict = JSON.parse(stdout);
    } catch {
      throw new SqlValidatorUnavailable(`sqlval produced no verdict (exit ${code}): ${stderr.slice(0, 2000)}`);
    }
    const cited = verdict.findings
      .map((f) => f.ref)
      .filter((r): r is string => typeof r === "string" && r.startsWith(`${system}.`));
    // Canonicalize to the snapshot's spelling: the statement may name an
    // object in any case, and the allow-set the token carries has to be
    // the FQN the visibility map is keyed by.
    const canonical = (refs: string[]): string[] =>
      refs.map((ref) => surface.allByLower.get(ref.toLowerCase()) ?? ref);
    return {
      ...base,
      verdict: verdict.verdict,
      findings: verdict.findings,
      statementSha256:
        verdict.verdict === "pass"
          ? verdict.statement_sha256 ?? createHash("sha256").update(statement).digest("hex")
          : null,
      citedObjects: canonical(verdict.verdict === "pass" ? verdict.referenced_objects ?? [] : cited),
      hiddenObjects: verdict.verdict === "pass" ? [] : hiddenAmong(surface, verdict.findings.map((f) => f.ref)),
    };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function identifierNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const names: string[] = [];
  for (const item of value) {
    if (typeof item === "string") names.push(item);
    else if (item && typeof item === "object" && typeof (item as { name?: unknown }).name === "string") {
      names.push((item as { name: string }).name);
    }
  }
  return names;
}

function validateApiDialect(
  ws: KbState,
  system: string,
  surface: VisibleSurface,
  request: Record<string, unknown>,
  base: ValidateOutcome,
): ValidateOutcome {
  const conventions = ws.guardrails[system] ?? {};
  const findings: Finding[] = [];
  const operation = typeof request.operation === "string" ? request.operation : "";
  const documentedOp = typeof conventions.operation === "string" ? conventions.operation : null;
  if (!operation) {
    findings.push({ severity: "error", code: "invalid_argument", ref: null, message: "request.operation required" });
  } else if (documentedOp && operation.toLowerCase() !== documentedOp.toLowerCase()) {
    findings.push({
      severity: "error",
      code: "unknown_operation",
      ref: operation,
      message: `system ${system} documents operation ${documentedOp}, got ${operation}`,
    });
  }
  const body = (request.body as Record<string, unknown> | undefined) ?? {};
  // Same rule as the SQL dialect: the documented surface this resolves
  // against is the caller's slice of it, so a hidden custom dimension is
  // "not in the documented surface" in exactly the words an undocumented
  // one gets (MT-8's message, MT-12's case).
  const byKindName = new Map<string, string>();
  for (const obj of surface.objects) {
    byKindName.set(`${obj.kind}:${obj.name.toLowerCase()}`, obj.fqn);
  }
  const cited: string[] = [];
  const hiddenObjects: string[] = [];
  /** Refused because hidden, or refused because absent? Audit-only. */
  const noteIfHidden = (kind: string, name: string): void => {
    const canonical = surface.allByKindName.get(`${kind}:${name.toLowerCase()}`);
    if (canonical && surface.hidden.has(canonical) && !hiddenObjects.includes(canonical)) {
      hiddenObjects.push(canonical);
    }
  };
  for (const dim of identifierNames(body.dimensions)) {
    const fqn = byKindName.get(`api_dimension:${dim.toLowerCase()}`);
    if (!fqn) {
      noteIfHidden("api_dimension", dim);
      findings.push({
        severity: "error",
        code: "unknown_dimension",
        ref: `${system}.${dim}`,
        message: `dimension ${dim} is not in the documented ${system} surface`,
      });
    } else cited.push(fqn);
  }
  for (const metric of identifierNames(body.metrics)) {
    const fqn = byKindName.get(`api_metric:${metric.toLowerCase()}`);
    if (!fqn) {
      noteIfHidden("api_metric", metric);
      findings.push({
        severity: "error",
        code: "unknown_metric",
        ref: `${system}.${metric}`,
        message: `metric ${metric} is not in the documented ${system} surface`,
      });
    } else cited.push(fqn);
  }
  if (findings.length > 0) {
    const citedFailing = findings.map((f) => f.ref).filter((r): r is string => r !== null);
    return { ...base, verdict: "fail", findings, citedObjects: citedFailing, hiddenObjects };
  }
  const canonical = canonicalJson({ operation, body });
  return {
    ...base,
    verdict: "pass",
    findings: [],
    statementSha256: createHash("sha256").update(canonical).digest("hex"),
    citedObjects: cited,
  };
}
