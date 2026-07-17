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
 */

import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import pg from "pg";
import type { CoreConfig } from "./config.js";
import { canonicalJson } from "./audit.js";
import type { KbState } from "./kbread.js";
import type { Profile } from "./profiles.js";
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

export async function validateRequest(
  cfg: CoreConfig,
  pool: pg.Pool,
  ws: KbState,
  identity: { subject: string },
  profile: Profile,
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

  let outcome: ValidateOutcome;
  if (dialect === "sql") {
    outcome = await validateSqlDialect(cfg, ws, system, request, base);
  } else {
    outcome = validateApiDialect(ws, system, request, base);
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
  request: Record<string, unknown>,
  base: ValidateOutcome,
): Promise<ValidateOutcome> {
  const statement = request.statement;
  if (typeof statement !== "string" || !statement.trim()) {
    return { ...base, error: { code: "invalid_argument", message: "request.statement (string) required" } };
  }
  const state = ws.systems.get(system)!;
  const conventions = ws.guardrails[system] ?? {};
  const objects = [...state.objects.values()].map((obj) => ({
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
    return {
      ...base,
      verdict: verdict.verdict,
      findings: verdict.findings,
      statementSha256:
        verdict.verdict === "pass"
          ? verdict.statement_sha256 ?? createHash("sha256").update(statement).digest("hex")
          : null,
      citedObjects: verdict.verdict === "pass" ? verdict.referenced_objects ?? [] : cited,
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
  request: Record<string, unknown>,
  base: ValidateOutcome,
): ValidateOutcome {
  const state = ws.systems.get(system)!;
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
  const byKindName = new Map<string, string>();
  for (const obj of state.objects.values()) {
    byKindName.set(`${obj.kind}:${obj.name.toLowerCase()}`, obj.fqn);
  }
  const cited: string[] = [];
  for (const dim of identifierNames(body.dimensions)) {
    const fqn = byKindName.get(`api_dimension:${dim.toLowerCase()}`);
    if (!fqn) {
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
    return { ...base, verdict: "fail", findings, citedObjects: citedFailing };
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
