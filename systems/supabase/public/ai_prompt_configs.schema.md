---
doc_class: machine-object
object: supabase.public.ai_prompt_configs
kind: table
schema_hash: "sha256:2df835a9e26fba31667cdb512f984a9464025f5903ff4b9d7161e2d4f86632b5"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.ai_prompt_configs`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.ai_prompt_configs` |
| Kind | table |
| Schema hash | `sha256:2df835a9e26fba31667cdb512f984a9464025f5903ff4b9d7161e2d4f86632b5` |

## Columns

| # | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — |
| 2 | `profile` | `text` | false | — | — |
| 3 | `flow_type` | `text` | false | — | — |
| 4 | `action_type` | `text` | true | — | — |
| 5 | `provider` | `text` | false | `'gemini'::text` | — |
| 6 | `model_name` | `text` | true | — | — |
| 7 | `prompt_key` | `text` | false | — | — |
| 8 | `prompt_version` | `text` | false | — | — |
| 9 | `system_prompt` | `text` | false | — | — |
| 10 | `user_prompt_template` | `text` | true | — | — |
| 11 | `is_active` | `boolean` | false | `true` | — |
| 12 | `created_at` | `timestamp with time zone` | false | `now()` | — |
| 13 | `updated_at` | `timestamp with time zone` | false | `now()` | — |

## Keys & indexes

Primary key: `id`

Foreign keys: —

Unique constraints: —

Indexes:

- `CREATE INDEX ai_prompt_configs_profile_lookup_idx ON public.ai_prompt_configs USING btree (profile, is_active, flow_type, action_type, provider)`
- `CREATE UNIQUE INDEX ai_prompt_configs_active_unique_idx ON public.ai_prompt_configs USING btree (profile, flow_type, COALESCE(action_type, ''::text), provider) WHERE (is_active = true)`

## Row estimate & freshness

Row estimate: 16

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
