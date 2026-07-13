---
doc_class: human-object
object: supabase.public.usage_counters
written_against_schema_hash: "sha256:a4d5722f8765986984bc078fbbc2c86f5d61231eed158555f8036067509b7eee"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/usage_counters.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate)"
depends_on:
  - supabase.public.usage_counters
  - supabase.public.users
---

# `supabase.public.usage_counters` (human doc)

Per-user, per-period usage accumulators:
`tailored_cv_generations_count`, `exports_count`, `ai_actions_count`
(all `integer`, default `0`) and `storage_bytes_used` (`bigint`,
default `0`). Structural facts are from
[usage_counters.schema.md](usage_counters.schema.md).

## Grain — attested by unique constraint

One row per `(user_id, period_month)` (unique constraint). Snapshot row
estimate: 33 (2026-07-12).

## Columns with grounded notes

- `period_month` (`date`, NOT NULL): the name implies monthly periods,
  but the schema does not constrain the value to a month boundary —
  whether it is always the first of the month is unverified (see PR
  gaps).
- The three `*_count` columns and `storage_bytes_used`: **increment
  rules are undocumented** — what exactly counts as a "tailored CV
  generation", an "export" (does it include cover-letter exports? only
  successes?), or an "AI action", and when `storage_bytes_used` is
  recomputed, is not stated anywhere in the schema. Only `updated_at`
  (default `now()`) hints at in-place updates.

## Join guidance (from FKs)

`user_id` → `users.id` (NOT NULL). Period-scoped joins key on
`(user_id, period_month)`.

## Warnings

- Do not reconcile these counters against the event tables
  (`exports`, `ai_runs`, …) and expect equality — the increment rules
  are undocumented, and the schema offers no guarantee they were
  incremented transactionally with those tables' writes. Treat counters
  and event-table counts as separate measurements until a customer
  source defines them.
