/**
 * The publish gateway (MCP spec §6.8, capability §8, formats §4.6 —
 * CP-7/M3).
 *
 * `publish_report` is the one tool that carries estate-derived content
 * *out* of the estate into a BI platform, so this module is where every
 * "did we check that?" about an artifact has exactly one answer:
 *
 * - **Structural validity (formats §4, FA-4).** The artifact parses
 *   against the §4 shape: envelope fields, query/backing shapes, the
 *   closed visual registry, and — non-negotiably — `entity_ref` on
 *   every blend key. A blend key without its entity doc is an
 *   improvised join wearing a schema violation as a costume.
 * - **MT-10 ref resolution.** Every metric/dimension/blend ref must
 *   resolve to a KB doc *visible to the caller* (M-4: a hidden doc is
 *   worded exactly like a missing one; the audit records the truth).
 *   A `certified: true` claim is checked against the doc's actual
 *   status — a report may not carry certification the KB never granted.
 * - **Blend keys come from the entity doc's documented mappings**
 *   (formats §4.5): both columns of every key must appear among the
 *   entity's `maps:` keys, or the publish is refused with the
 *   documented keys named in the error.
 * - **F-7 re-validation.** Every query's `validated_against` pin must
 *   match the current snapshot AND the request must still validate
 *   (token-less — an artifact is not a bypass around the validation
 *   gate, and re-validation never mints an execution right).
 * - **Persistence + idempotency (F-5/F-6/FM-3).** Revisions are
 *   server-assigned per content hash; same (id, target, hash)
 *   short-circuits to the stored result without enqueueing; a new hash
 *   updates, never duplicates (PB-2).
 * - **F-4 lineage effects.** On success, gateway-tier attestations
 *   (tier `pipeline-tool`, ref `gateway:<audit-id>`, F-3) are persisted
 *   for every query backing → report node, feeding the next graph
 *   regeneration's input set.
 */

import { createHash } from "node:crypto";
import pg from "pg";
import { canonicalJson } from "./audit.js";
import type { CoreConfig } from "./config.js";
import type { KbState } from "./kbread.js";
import type { Profile } from "./profiles.js";
import { awaitJobResult, enqueue, EnqueueError } from "./queue.js";
import { interactiveDeadlineS } from "./registry.js";
import { getSyncSystem } from "./triggers.js";
import { validateRequest } from "./valsql.js";
import { pathVisible } from "./visibility.js";

/** Formats spec §4.4 registry v1 — closed set, additive growth only. */
export const VISUAL_KINDS = new Set(["table", "line", "bar", "scorecard", "pivot"]);
const BACKING_MODES = new Set(["direct", "reporting_view", "dataset_ref"]);

export interface PublishIdentity {
  subject: string;
  roles: string[];
  display?: string | null;
}

export interface PublishOutcome {
  ok: boolean;
  code?: string;
  message?: string;
  detail?: Record<string, unknown>;
  /** Capability §8.2 result, verbatim, when ok. */
  result?: Record<string, unknown>;
  /** Server-assigned artifact identity facts (additive to §8.2). */
  artifactInfo?: { id: string; revision: number; content_hash: string };
  meta: Record<string, unknown>;
  /** §8 audit text for publish — identity + content pin; the artifact
   * body itself is the deep store (report_artifacts). */
  statementText: string;
}

interface Notifier {
  waitFor(match: (payload: string | undefined) => boolean, ms: number): Promise<void>;
}

export interface PublishDeps {
  pool: pg.Pool;
  cfg: CoreConfig;
  notifier: Notifier;
  ws: KbState;
  identity: PublishIdentity;
  profile: Profile;
  scopes: string[];
  sessionId: string | null;
  auditId: string;
}

/** Structural findings against formats §4; empty = shape holds. */
export function artifactProblems(artifact: Record<string, unknown>): string[] {
  const problems: string[] = [];
  const need = (cond: boolean, msg: string) => {
    if (!cond) problems.push(msg);
  };

  need(artifact.artifact_version === "1", "artifact_version must be \"1\"");
  need(
    typeof artifact.id === "string" && (artifact.id as string).length >= 8,
    "id (stable artifact UUID string, formats §4.1/F-5) is required",
  );
  need(typeof artifact.title === "string" && (artifact.title as string).length > 0, "title is required");

  const queries = artifact.queries;
  if (!Array.isArray(queries) || queries.length === 0) {
    problems.push("queries must be a non-empty array");
  } else {
    queries.forEach((q, i) => {
      const query = (q ?? {}) as Record<string, unknown>;
      const label = `queries[${i}]`;
      need(typeof query.name === "string" && query.name !== "", `${label}.name is required`);
      need(typeof query.system === "string" && query.system !== "", `${label}.system is required`);
      const request = (query.request ?? {}) as Record<string, unknown>;
      if (request.dialect === "sql") {
        need(typeof request.statement === "string", `${label}.request.statement is required for dialect sql`);
      } else if (request.dialect === "api") {
        need(typeof request.operation === "string", `${label}.request.operation is required for dialect api`);
      } else {
        problems.push(`${label}.request.dialect must be "sql" or "api"`);
      }
      need(
        typeof query.validated_against === "string" && (query.validated_against as string).startsWith("sha256:"),
        `${label}.validated_against (snapshot pin, F-7) is required`,
      );
      const backing = (query.backing ?? {}) as Record<string, unknown>;
      if (!BACKING_MODES.has(backing.mode as string)) {
        problems.push(`${label}.backing.mode must be one of direct | reporting_view | dataset_ref`);
      } else if (backing.mode !== "direct") {
        need(
          typeof backing.ref === "string" && backing.ref !== "",
          `${label}.backing.ref is required for mode ${backing.mode}`,
        );
      }
    });
  }

  const semantics = (artifact.semantics ?? {}) as Record<string, unknown>;
  for (const field of ["metrics", "dimensions"] as const) {
    const entries = semantics[field];
    if (entries === undefined) continue;
    if (!Array.isArray(entries)) {
      problems.push(`semantics.${field} must be an array`);
      continue;
    }
    entries.forEach((entry, i) => {
      const e = (entry ?? {}) as Record<string, unknown>;
      need(typeof e.column === "string" && e.column !== "", `semantics.${field}[${i}].column is required`);
      need(typeof e.ref === "string" && e.ref !== "", `semantics.${field}[${i}].ref is required`);
    });
  }
  if (semantics.trust_notes !== undefined && !Array.isArray(semantics.trust_notes)) {
    problems.push("semantics.trust_notes must be an array of strings");
  }

  const queryNames = new Set(
    (Array.isArray(queries) ? queries : [])
      .map((q) => ((q ?? {}) as Record<string, unknown>).name)
      .filter((n): n is string => typeof n === "string"),
  );
  const visuals = artifact.visuals;
  if (visuals !== undefined) {
    if (!Array.isArray(visuals)) {
      problems.push("visuals must be an array");
    } else {
      visuals.forEach((v, i) => {
        const visual = (v ?? {}) as Record<string, unknown>;
        if (!VISUAL_KINDS.has(visual.kind as string)) {
          problems.push(
            `visuals[${i}].kind ${JSON.stringify(visual.kind)} is outside the §4.4 registry ` +
              `(${[...VISUAL_KINDS].join(" | ")})`,
          );
        }
        if (typeof visual.query === "string" && !queryNames.has(visual.query)) {
          problems.push(`visuals[${i}].query ${JSON.stringify(visual.query)} names no artifact query`);
        }
      });
    }
  }

  const blend = artifact.blend;
  if (blend !== null && blend !== undefined) {
    const b = blend as Record<string, unknown>;
    const keys = b.keys;
    if (!Array.isArray(keys) || keys.length === 0) {
      problems.push("blend.keys must be a non-empty array (formats §4.5)");
    } else {
      keys.forEach((k, i) => {
        const key = (k ?? {}) as Record<string, unknown>;
        need(typeof key.left_column === "string" && key.left_column !== "", `blend.keys[${i}].left_column is required`);
        need(typeof key.right_column === "string" && key.right_column !== "", `blend.keys[${i}].right_column is required`);
        // FA-4: a blend key without entity_ref is schema-invalid — and,
        // more importantly, an improvised join.
        need(
          typeof key.entity_ref === "string" && key.entity_ref !== "",
          `blend.keys[${i}].entity_ref is required — blend keys come from the entity ` +
            "doc's documented mappings, never improvised (formats §4.5)",
        );
      });
    }
  }

  return problems;
}

/** Documented blend-key columns of an entity doc: union of `maps[].keys`. */
function documentedEntityKeys(ws: KbState, entityRef: string): Set<string> {
  const doc = ws.docs.get(entityRef);
  const keys = new Set<string>();
  const maps = doc?.fm?.maps;
  if (Array.isArray(maps)) {
    for (const entry of maps) {
      const entryKeys = (entry as Record<string, unknown> | null)?.keys;
      if (Array.isArray(entryKeys)) {
        for (const key of entryKeys) if (typeof key === "string") keys.add(key);
      }
    }
  }
  return keys;
}

export async function publishReport(
  deps: PublishDeps,
  args: { artifact: Record<string, unknown>; target: string },
): Promise<PublishOutcome> {
  const { pool, cfg, ws, identity, profile } = deps;
  const artifact = args.artifact;
  const target = args.target;
  const artifactId = typeof artifact.id === "string" ? artifact.id : null;

  // Canonical body: the server owns revision/content_hash, so any
  // client-supplied copies are stripped before hashing (F-5: the hash
  // is change detection over content, not over bookkeeping).
  const body: Record<string, unknown> = { ...artifact };
  delete body.revision;
  delete body.content_hash;
  const contentHash = `sha256:${createHash("sha256").update(canonicalJson(body)).digest("hex")}`;
  const statementText = `publish_report target=${target} artifact=${artifactId ?? "(missing id)"} content=${contentHash}`;

  const decided: Record<string, unknown> = { target, artifact_id: artifactId, content_hash: contentHash };
  const fail = (
    code: string,
    message: string,
    extra: Record<string, unknown> = {},
    metaOnly: Record<string, unknown> = {},
  ): PublishOutcome => ({
    ok: false,
    code,
    message,
    ...(Object.keys(extra).length > 0 ? { detail: extra } : {}),
    meta: { ...decided, error: code, ...extra, ...metaOnly },
    statementText,
  });

  // --- formats §4 structural validation (FA-4) ------------------------------
  const problems = artifactProblems(artifact);
  if (problems.length > 0) {
    return fail("invalid_argument", `artifact fails the formats §4 shape: ${problems.join("; ")}`, {
      problems,
    });
  }

  // --- MT-10: every cited ref resolves, on the caller's visible surface -----
  const semantics = (artifact.semantics ?? {}) as Record<string, unknown>;
  const refs: { ref: string; kind: "metric" | "dimension" | "entity"; certified?: boolean }[] = [];
  for (const entry of (semantics.metrics as Record<string, unknown>[] | undefined) ?? []) {
    refs.push({ ref: entry.ref as string, kind: "metric", certified: entry.certified === true });
  }
  for (const entry of (semantics.dimensions as Record<string, unknown>[] | undefined) ?? []) {
    refs.push({ ref: entry.ref as string, kind: "dimension" });
  }
  const blend = (artifact.blend ?? null) as Record<string, unknown> | null;
  const blendKeys = (blend?.keys as Record<string, unknown>[] | undefined) ?? [];
  for (const key of blendKeys) refs.push({ ref: key.entity_ref as string, kind: "entity" });

  const unresolved: string[] = [];
  const hidden: string[] = [];
  for (const { ref } of refs) {
    const exists = ws.docs.has(ref);
    const visible = exists && pathVisible(deps.scopes, ref);
    if (!exists) unresolved.push(ref);
    else if (!visible) {
      // M-4: worded exactly like a missing doc; the truth goes to audit.
      unresolved.push(ref);
      hidden.push(ref);
    }
  }
  if (unresolved.length > 0) {
    return {
      ok: false,
      code: "config_error",
      message:
        `artifact cites context that does not resolve in the KB: ${[...new Set(unresolved)].sort().join(", ")} ` +
        "— a report may not cite context that doesn't exist (MT-10)",
      meta: {
        ...decided,
        error: "config_error",
        unresolved_refs: [...new Set(unresolved)].sort(),
        ...(hidden.length > 0 ? { filtered: true, hidden_refs: hidden.sort() } : {}),
      },
      statementText,
    };
  }

  // Certification honesty: `certified: true` must match the doc.
  const falseCertified = refs.filter(({ ref, certified }) => {
    if (!certified) return false;
    const doc = ws.docs.get(ref);
    return doc?.fm?.status !== "verified";
  });
  if (falseCertified.length > 0) {
    return fail(
      "config_error",
      "artifact claims certification the KB does not grant: " +
        falseCertified.map((r) => r.ref).sort().join(", ") +
        " (get_metric flags certified only for status: verified)",
      { uncertified_refs: falseCertified.map((r) => r.ref).sort() },
    );
  }

  // Blend keys must be the entity doc's documented mappings (§4.5).
  for (const key of blendKeys) {
    const entityRef = key.entity_ref as string;
    const documented = documentedEntityKeys(ws, entityRef);
    const missing = [key.left_column, key.right_column].filter(
      (column) => typeof column === "string" && !documented.has(column),
    );
    if (missing.length > 0) {
      return fail(
        "config_error",
        `blend key ${key.left_column}×${key.right_column} cites ${entityRef}, which documents ` +
          `keys [${[...documented].sort().join(", ")}] — ${missing.join(" and ")} ` +
          "is not among them. Blend only on documented entity keys (formats §4.5); " +
          "if the mapping is real, enrich the entity doc first (flag_gap: missing_join_path).",
        { entity_ref: entityRef, undocumented_columns: missing, documented_keys: [...documented].sort() },
      );
    }
  }

  // --- F-7: snapshot pins current + queries still validate ------------------
  const citedByQuery = new Map<string, string[]>();
  for (const q of artifact.queries as Record<string, unknown>[]) {
    const system = q.system as string;
    const state = ws.systems.get(system);
    if (!state) {
      return fail("config_error", `no accepted snapshot for system ${system} (query ${q.name})`);
    }
    const currentRef = `sha256:${state.canonicalBodySha256.replace(/^sha256:/, "")}`;
    if (q.validated_against !== currentRef) {
      // FA-2: the schema moved since drafting — clean revalidate_required,
      // nothing reaches the adapter.
      return fail("revalidate_required", `query ${q.name} was validated against a snapshot that is no longer current for ${system}; re-validate and re-emit the artifact`, {
        query: q.name,
        system,
        pinned: q.validated_against,
        current: currentRef,
      });
    }
    const outcome = await validateRequest(
      cfg,
      pool,
      ws,
      { subject: identity.subject },
      profile,
      deps.scopes,
      { system, request: q.request as Record<string, unknown> },
      { issueToken: false },
    );
    if (outcome.error) {
      return fail(outcome.error.code === "invalid_argument" ? "invalid_argument" : "config_error",
        `query ${q.name}: ${outcome.error.message}`);
    }
    if (outcome.verdict !== "pass") {
      return {
        ok: false,
        code: "revalidate_required",
        message:
          `query ${q.name} no longer validates against the current snapshot: ` +
          outcome.findings.map((f) => f.message).join("; "),
        detail: { query: q.name, findings: outcome.findings },
        meta: {
          ...decided,
          error: "revalidate_required",
          query: q.name,
          finding_codes: outcome.findings.map((f) => f.code),
          ...(outcome.hiddenObjects.length > 0
            ? { filtered: true, hidden_objects: outcome.hiddenObjects }
            : {}),
        },
        statementText,
      };
    }
    citedByQuery.set(q.name as string, outcome.citedObjects);
  }

  // --- target registration ---------------------------------------------------
  const registration = await getSyncSystem(pool, target);
  if (!registration) {
    return fail(
      "config_error",
      `target ${target} has no connection registered; register the publisher connection ` +
        "(cli sync systems set) before publishing to it",
    );
  }

  // --- persist artifact; assign revision (F-5, FM-3) -------------------------
  const { rows: priorRevisions } = await pool.query<{ revision: number; content_hash: string }>(
    `SELECT revision, content_hash FROM report_artifacts WHERE artifact_id = $1 ORDER BY revision`,
    [artifactId],
  );
  const existing = priorRevisions.find((r) => r.content_hash === contentHash);
  const revision = existing?.revision ?? (priorRevisions.at(-1)?.revision ?? 0) + 1;
  if (!existing) {
    await pool.query(
      `INSERT INTO report_artifacts (artifact_id, revision, content_hash, body, created_by, kb_ref)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [artifactId, revision, contentHash, canonicalJson(body), identity.subject,
       typeof artifact.kb_ref === "string" ? artifact.kb_ref : null],
    );
  }
  decided.revision = revision;

  // --- idempotency short-circuit (§4.6, FA-3) --------------------------------
  const { rows: priorPublish } = await pool.query<{
    content_hash: string;
    revision: number;
    result: Record<string, unknown>;
    job_id: string | null;
  }>(
    `SELECT content_hash, revision, result, job_id FROM publish_results
      WHERE artifact_id = $1 AND target = $2`,
    [artifactId, target],
  );
  if (priorPublish[0] && priorPublish[0].content_hash === contentHash) {
    return {
      ok: true,
      result: priorPublish[0].result,
      artifactInfo: { id: artifactId!, revision: priorPublish[0].revision, content_hash: contentHash },
      meta: {
        ...decided,
        short_circuit: true,
        prior_job_id: priorPublish[0].job_id,
        created_urls: createdUrls(priorPublish[0].result),
      },
      statementText,
    };
  }

  // --- enqueue the interactive publish job (§8.2 payload) --------------------
  const registrationPayload = registration.payload as {
    config?: Record<string, unknown>;
    credentials?: { required_for?: unknown }[];
  };
  const jobPayload = {
    config: { ...(registrationPayload.config ?? {}) },
    // Publish jobs carry only credentials marked for the publish
    // capability. Template-link adapters declare none — deliberately;
    // nothing here fails closed on empty, unlike execute, because the
    // credential-less path is the designed one (no secret rides a URL).
    credentials: (registrationPayload.credentials ?? []).filter((entry) => {
      const requiredFor = entry?.required_for;
      return Array.isArray(requiredFor) && requiredFor.includes("publish");
    }),
    identity: {
      subject: identity.subject,
      roles: identity.roles,
      ...(identity.display ? { display: identity.display } : {}),
      ...(deps.sessionId ? { session_id: deps.sessionId } : {}),
    },
    artifact: { ...body, revision },
    target,
  };

  let jobId: string;
  try {
    ({ jobId } = await enqueue(pool, cfg, {
      type: "publish",
      system: target,
      connector: {
        name: registration.connector_name,
        version_constraint: registration.version_constraint,
      },
      payload: jobPayload,
      deadline_s: interactiveDeadlineS(undefined),
      trigger: { kind: "gateway", detail: { audit_id: deps.auditId } },
    }));
  } catch (err) {
    if (err instanceof EnqueueError) {
      return fail("config_error", `publish job rejected: ${err.problems.join("; ")}`);
    }
    throw err;
  }

  const awaitMs = interactiveDeadlineS(undefined) * 1000;
  const awaited = await awaitJobResult(pool, deps.notifier, jobId, awaitMs);
  const baseMeta = { ...decided, job_id: jobId };

  if (awaited.status === "timeout") {
    return {
      ok: false,
      code: "upstream_error",
      message: `publish did not complete within ${interactiveDeadlineS(undefined)}s`,
      meta: { ...baseMeta, error: "upstream_error", reason: "deadline" },
      statementText,
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
    return {
      ok: false,
      code: error.code === "guardrail" ? "guardrail" : "upstream_error",
      message: error.message ?? "publish failed",
      detail: {
        ...(capabilityCode ? { capability_code: capabilityCode } : {}),
        job_error: { code: error.code, message: error.message },
      },
      meta: {
        ...baseMeta,
        error: error.code ?? "upstream_error",
        ...(capabilityCode ? { guardrail_code: capabilityCode } : {}),
      },
      statementText,
    };
  }

  const result = (awaited.result ?? {}) as Record<string, unknown>;

  // --- persist the publish result (PB-2: update, never duplicate) ------------
  await pool.query(
    `INSERT INTO publish_results (artifact_id, target, revision, content_hash, result, audit_ref, job_id)
     VALUES ($1, $2, $3, $4, $5, $6, $7)
     ON CONFLICT (artifact_id, target) DO UPDATE
       SET revision = EXCLUDED.revision, content_hash = EXCLUDED.content_hash,
           result = EXCLUDED.result, audit_ref = EXCLUDED.audit_ref,
           job_id = EXCLUDED.job_id, published_at = now()`,
    [artifactId, target, revision, contentHash, JSON.stringify(result), deps.auditId, jobId],
  );

  // --- F-4: gateway-tier attestations into the next regeneration ------------
  const publisherId = firstCreatedId(result);
  if (publisherId) {
    const reportNode = `${target}.report.${publisherId}`;
    const evidence = { tier: "pipeline-tool", ref: `gateway:${deps.auditId}` };
    const targetMeta = { resolved: true, kind: "report", schema: null, name: publisherId };
    const sources = new Map<string, { resolved: boolean; kind: string; schema: string | null; name: string }>();
    for (const q of artifact.queries as Record<string, unknown>[]) {
      const system = q.system as string;
      const backing = (q.backing ?? {}) as Record<string, unknown>;
      const fqns =
        backing.mode === "direct"
          ? citedByQuery.get(q.name as string) ?? []
          : [`${system}.${backing.ref as string}`];
      for (const fqn of fqns) {
        const obj = ws.systems.get(system)?.objects.get(fqn);
        sources.set(
          fqn,
          obj
            ? { resolved: true, kind: obj.kind, schema: obj.schema, name: obj.name }
            : { resolved: false, kind: "external", schema: null, name: fqn.split(".").at(-1) ?? fqn },
        );
      }
    }
    for (const [fqn, sourceMeta] of [...sources.entries()].sort(([a], [b]) => (a < b ? -1 : 1))) {
      await pool.query(
        `INSERT INTO lineage_attestations
           (source_fqn, target_fqn, operation, evidence, source_meta, target_meta, audit_ref)
         VALUES ($1, $2, 'ingest', $3, $4, $5, $6)
         ON CONFLICT (source_fqn, target_fqn, operation) DO UPDATE
           SET evidence = EXCLUDED.evidence, source_meta = EXCLUDED.source_meta,
               target_meta = EXCLUDED.target_meta, audit_ref = EXCLUDED.audit_ref`,
        [fqn, reportNode, JSON.stringify(evidence), JSON.stringify(sourceMeta),
         JSON.stringify(targetMeta), deps.auditId],
      );
    }
  }

  return {
    ok: true,
    result,
    artifactInfo: { id: artifactId!, revision, content_hash: contentHash },
    meta: {
      ...baseMeta,
      mode: typeof result.mode === "string" ? result.mode : null,
      created_urls: createdUrls(result),
      pending_steps: Array.isArray(result.pending_human_steps) ? result.pending_human_steps.length : 0,
    },
    statementText,
  };
}

function firstCreatedId(result: Record<string, unknown>): string | null {
  const created = result.created;
  if (!Array.isArray(created) || created.length === 0) return null;
  const id = (created[0] as Record<string, unknown> | null)?.id;
  return typeof id === "string" && id !== "" ? id : null;
}

/** §8 audit contract: created URLs are the publish result_meta. */
function createdUrls(result: Record<string, unknown>): string[] {
  const created = result.created;
  if (!Array.isArray(created)) return [];
  return created
    .map((entry) => (entry as Record<string, unknown> | null)?.url)
    .filter((url): url is string => typeof url === "string");
}
