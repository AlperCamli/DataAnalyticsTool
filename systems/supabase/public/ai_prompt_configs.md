---
doc_class: human-object
object: supabase.public.ai_prompt_configs
written_against_schema_hash: "sha256:2df835a9e26fba31667cdb512f984a9464025f5903ff4b9d7161e2d4f86632b5"
status: draft
last_verified: null
purpose: "Configurable prompt records resolved at runtime to supply system/user templates for AI flows by profile, provider, and action."
column_purposes:
  id: "Internal prompt-config id."
  profile: "Named prompt profile this config belongs to (e.g. phase3-v1)."
  flow_type: "AI flow this prompt targets; enum in body."
  action_type: "Optional block action this prompt targets; enum in body."
  provider: "Provider this prompt is registered for; 'any' is the fallback."
  model_name: "Specific model this prompt is pinned to, or null for provider default."
  prompt_key: "Stable lookup key identifying the prompt content (e.g. cv-parse)."
  prompt_version: "Semantic version label of the prompt content (e.g. phase5-v3)."
  system_prompt: "System prompt body sent to the model."
  user_prompt_template: "Optional user prompt template body."
  is_active: "Whether this row is eligible for runtime resolution."
  created_at: "When the prompt config was created."
  updated_at: "When the prompt config was last updated."
sources:
  - "customer doc: cv-data-model-kb/CV_data_tool/tables/ai_prompt_configs.md"
  - "app DDL: CV_Builder/backend/supabase/migrations (ai_prompt_configs_flow_type_check, ai_prompt_configs_action_type_check)"
  - "machine doc: supabase.public.ai_prompt_configs"
depends_on:
  - supabase.public.ai_runs
contamination: null
---

# `supabase.public.ai_prompt_configs`

## Grain

One row per registered prompt variant. A **partial unique** index enforces at
most one **active** prompt per `(profile, flow_type, coalesce(action_type,''),
provider)` (`where is_active = true`) — that tuple is the runtime resolution
key. No `user_id`: this is shared configuration, not user data.

## Column meanings & enum decodings

- `flow_type` — DB-constrained (`ai_prompt_configs_flow_type_check`) to:
  **`job_analysis`, `follow_up_questions`, `tailored_draft`, `block_suggest`,
  `block_compare`, `multi_option`, `import_improve`, `summary`, `improve`,
  `cv_parse`, `cover_letter_generation`**. Same set as
  `supabase.public.ai_runs.flow_type`.
- `action_type` (nullable) — for block-level flows, DB-constrained to
  **`rewrite`, `summarize`, `improve`, `ats_optimize`, `options`, `expand`,
  `shorten`**. `null` when the flow is not block-scoped.
- `provider` — default `gemini`; the sentinel **`any`** matches any provider
  as a fallback during resolution.

## Join guidance

No FKs. It is joined only implicitly: `supabase.public.ai_runs` records the
`flow_type`/`provider`/`model_name` actually used, but does **not** carry a FK
to the resolved `ai_prompt_configs` row — there is no stored link between a run
and the prompt version it used.

## Reporting notes

- To audit which prompts are live, filter `is_active = true` and group by
  `(profile, flow_type, action_type, provider)`.
- `prompt_version`/`prompt_key` are the human-facing content identifiers for
  change tracking.

## Warnings

- **No run→prompt linkage** — you cannot join a specific `ai_run` to the exact
  prompt row it resolved; only the flow/provider/model are recorded on the run.
- `system_prompt`/`user_prompt_template` are free text; no structure to decode.
