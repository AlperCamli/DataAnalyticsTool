/**
 * Job type registry (job spec §4.2) with the §4.2 class defaults.
 * Growth is additive. Only `snapshot` has a delivery pipeline in CP-3a;
 * the rest are registered so enqueue/claim/lease machinery treats them
 * uniformly, and their results (when a runner someday declares them)
 * are stored inline on the job without further processing.
 */

export type JobClass = "batch" | "interactive";

export interface JobTypeSpec {
  type: string;
  class: JobClass;
  /** Has a CP-3a result pipeline (J-6 validation + acceptance store). */
  implemented: boolean;
}

export const CLASS_DEFAULTS: Record<
  JobClass,
  { priority: number; deadlineS: number; maxAttempts: number }
> = {
  batch: { priority: 50, deadlineS: 3600, maxAttempts: 5 },
  // Interactive deadline is normatively derived from the gateway
  // guardrail (§4.2); no gateway exists until CP-6, so a conservative
  // fixed default stands in.
  interactive: { priority: 10, deadlineS: 120, maxAttempts: 1 },
};

export const JOB_TYPES: ReadonlyMap<string, JobTypeSpec> = new Map(
  (
    [
      { type: "snapshot", class: "batch", implemented: true },
      { type: "harvest", class: "batch", implemented: false },
      { type: "lineage", class: "batch", implemented: false },
      { type: "usage", class: "batch", implemented: false },
      { type: "test_connection", class: "interactive", implemented: false },
      { type: "execute", class: "interactive", implemented: false },
      { type: "publish", class: "interactive", implemented: false },
    ] as JobTypeSpec[]
  ).map((spec) => [spec.type, spec]),
);

export const TRIGGER_KINDS = ["schedule", "webhook", "manual", "gateway", "dashboard"] as const;

/** Normative §6.7 error codes; unknown codes are accepted (additive) but
 * retryability then comes only from the envelope's own flag. */
export const ERROR_CODES = new Set([
  "config_error",
  "auth_error",
  "source_unavailable",
  "quota",
  "validation_error",
  "guardrail",
  "cancelled",
  "internal",
]);
