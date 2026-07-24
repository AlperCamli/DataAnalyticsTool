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
  // §4.2: interactive `deadline_s` is derived from the gateway
  // guardrail (statement timeout + margin) — see `interactiveDeadlineS`.
  // This value applies only when a producer enqueues without one.
  interactive: { priority: 10, deadlineS: 120, maxAttempts: 1 },
};

/**
 * §4.2's "deadline_s derived from the gateway guardrail (statement
 * timeout + margin)". The margin covers claim, connect, and delivery —
 * everything around the statement that the statement timeout itself
 * does not bound. Without it, a query using its full timeout budget
 * would race its own job deadline and surface as a lease expiry rather
 * than the honest `timeout` guardrail.
 */
export const INTERACTIVE_DEADLINE_MARGIN_S = 30;

export function interactiveDeadlineS(timeoutS: number | undefined): number {
  if (typeof timeoutS !== "number" || !Number.isFinite(timeoutS) || timeoutS <= 0) {
    return CLASS_DEFAULTS.interactive.deadlineS;
  }
  return Math.ceil(timeoutS) + INTERACTIVE_DEADLINE_MARGIN_S;
}

export const JOB_TYPES: ReadonlyMap<string, JobTypeSpec> = new Map(
  (
    [
      { type: "snapshot", class: "batch", implemented: true },
      { type: "harvest", class: "batch", implemented: false },
      { type: "lineage", class: "batch", implemented: false },
      { type: "usage", class: "batch", implemented: false },
      { type: "test_connection", class: "interactive", implemented: false },
      // CP-6: the execution gateway is the producer; results are relayed
      // inline to the blocked caller (§6.4).
      { type: "execute", class: "interactive", implemented: true },
      // CP-7: the publish gateway (MCP §6.8) is the producer.
      { type: "publish", class: "interactive", implemented: true },
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
