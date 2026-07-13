---
doc_class: human-object
object: supabase.public.ai_runs
written_against_schema_hash: "sha256:1371cc0551146b3167888b67d16ddbf8c054f90222a4cb07b3312d9a18a89497"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/ai_runs.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate, referenced-by)"
depends_on:
  - supabase.public.ai_runs
  - supabase.public.users
  - supabase.public.master_cvs
  - supabase.public.tailored_cvs
  - supabase.public.jobs
  - supabase.public.ai_suggestions
---

# `supabase.public.ai_runs` (human doc)

One row per AI invocation: `flow_type`, `provider`, `model_name`,
input/output payloads (`jsonb`), token counts, and a
`status`/`progress_stage` pair with `started_at`/`completed_at`
timestamps. The largest table in the snapshot (row estimate 518,
2026-07-12). Structural facts are from
[ai_runs.schema.md](ai_runs.schema.md).

## Grain

One row per `id` (primary key, `uuid`). No unique constraints beyond
the PK.

## Columns with grounded notes

- `status` (`text`, NOT NULL, no default) and `progress_stage` (`text`,
  NOT NULL, default `'queued'`): only `'queued'` (the progress_stage
  default) is attested anywhere; both vocabularies and the distinction
  between the two columns are undocumented (see PR gaps). Indexed
  together as `(user_id, status, progress_stage, started_at DESC)` and
  `(flow_type, status)`.
- `master_cv_id`, `tailored_cv_id`, `job_id`: all nullable FKs; no
  CHECK constrains which combination a given `flow_type` uses.
- `input_tokens` / `output_tokens` / `total_tokens` (`integer`,
  nullable): whether `total = input + output`, and which tokenizer,
  are undocumented.
- `debug_payload` (`jsonb`, nullable), `error_message` (nullable):
  shapes undocumented.

## Join guidance (from FKs)

`user_id` → `users.id` (NOT NULL); `master_cv_id` → `master_cvs.id`;
`tailored_cv_id` → `tailored_cvs.id`; `job_id` → `jobs.id` (all
nullable). Referenced by `ai_suggestions.ai_run_id` (NOT NULL there) —
every suggestion traces to exactly one run.

## Warnings

- Cost/usage analyses on token columns must handle NULLs (all three are
  nullable) and cannot assume a provider-uniform token definition.
- Run success/failure filters need the `status` vocabulary — currently
  undocumented; `completed_at IS NOT NULL` is attested structure but
  its equivalence to "finished successfully" is not.
- `usage_counters.ai_actions_count` is not documented as derived from
  this table; do not reconcile them (see
  [usage_counters.schema.md](usage_counters.schema.md)).
