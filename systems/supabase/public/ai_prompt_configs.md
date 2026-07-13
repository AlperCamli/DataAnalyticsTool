---
doc_class: human-object
object: supabase.public.ai_prompt_configs
written_against_schema_hash: "sha256:2df835a9e26fba31667cdb512f984a9464025f5903ff4b9d7161e2d4f86632b5"
status: draft
last_verified: null
sources:
  - "systems/supabase/public/ai_prompt_configs.schema.md (machine snapshot, generated_at 2026-07-12: columns, keys, indexes, row estimate)"
depends_on:
  - supabase.public.ai_prompt_configs
---

# `supabase.public.ai_prompt_configs` (human doc)

Prompt configuration rows for the product's AI flows: a `system_prompt`
(NOT NULL) and optional `user_prompt_template`, versioned by
`prompt_key`/`prompt_version`, selected by
(`profile`, `flow_type`, `action_type`, `provider`). Not user-scoped —
no `user_id` column, and the only table in this schema with no foreign
keys in either direction. Structural facts are from
[ai_prompt_configs.schema.md](ai_prompt_configs.schema.md).

## Grain

One row per `id` (primary key, `uuid`). Partial unique index
`ai_prompt_configs_active_unique_idx` on
`(profile, flow_type, COALESCE(action_type, ''), provider)` WHERE
`is_active = true`: **at most one active config per selector
combination** (NULL `action_type` collapses to `''` for uniqueness).
Snapshot row estimate: 16 (2026-07-12).

## Columns with grounded notes

- `provider` (`text`, NOT NULL) defaults to `'gemini'` — the only
  provider value the schema attests. `model_name` is nullable.
- `profile`, `flow_type`, `action_type`, `prompt_key`,
  `prompt_version`: vocabularies undocumented (see PR gaps).
  `ai_runs.flow_type` shares the name `flow_type`, but there is no FK —
  whether the vocabularies match is undocumented.
- `is_active` (`boolean`, NOT NULL, default `true`): inactive rows are
  retained, so this table doubles as config history.

## Join guidance

None enforced — no FKs. Any join to `ai_runs` (e.g. on
`provider`/`model_name`/`flow_type`) is name-based and must be labeled
as such.

## Warnings

- "Current config" queries must filter `is_active = true`; without it
  you read superseded versions.
