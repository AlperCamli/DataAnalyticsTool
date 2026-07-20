---
doc_class: human-object
object: supabase.reporting.v_ai_runs_by_flow
written_against_schema_hash: "sha256:decb62fc93c17415b1901bbbdabe0f4676c767f640007addbb7f5aad904e1ece"
status: draft
last_verified: null
purpose: "AI invocation volume, token consumption and latency, split by flow, provider, model and outcome."
column_purposes:
  flow_type: "Logical AI flow executed; the same enum as `public.ai_runs.flow_type`."
  provider: "AI provider that served the run."
  model_name: "Specific model used."
  status: "Terminal status of the run (`pending` | `completed` | `failed`)."
  run_count: "Runs matching this combination."
  distinct_users: "Users who triggered at least one such run."
  input_tokens: "Sum of input tokens; null-valued rows contribute nothing."
  output_tokens: "Sum of output tokens."
  total_tokens: "Sum of billed tokens — the figure to use for cost."
  avg_seconds: "Mean wall-clock seconds from `started_at` to `completed_at`, to 2dp."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_ai_runs_by_flow"
  - "human doc: supabase.public.ai_runs"
depends_on:
  - supabase.public.ai_runs
contamination: null
---

# `supabase.reporting.v_ai_runs_by_flow`

## Grain

One row per (flow_type, provider, model_name, status) combination observed.

## Reporting notes

- The cost view: `total_tokens` is the figure the source data designates for
  cost estimation, per the `ai_runs` semantics.
- Success rate per flow = `run_count` where `status='completed'` over the flow's
  total. Filtering to `status='failed'` and ordering by `run_count` surfaces the
  flows worth fixing first.
- `avg_seconds` per (flow, model) is the latency comparison for model choice.

## Warnings

- **These are aggregate views over row-level-security-protected tables.** The
  base tables (`public.*`) enforce per-user RLS, so the execution role reads
  **zero rows** from them directly. These views answer anyway because a view
  evaluates RLS as its *owner*, and they are owned by a role that bypasses it.
  That is a deliberate, narrow opening — and it is why every column here is an
  aggregate or a non-identifying dimension. Do not expect to drill from these
  numbers to a person: no view exposes `user_id`, an email, a name, or any free
  text a user wrote.
- **Small counts can still identify.** The estate is ~24 users. A group of size
  1–2 is potentially personal even though no column names anyone; treat such
  cells as sensitive rather than reportable.
- **`avg_seconds` only covers runs that finished.** `completed_at` is null
  until a run terminates, so pending runs contribute nothing to the average — a
  flow that habitually hangs will look fast here.
- Token columns are **nullable on older rows**; the sums silently skip them, so
  a total is a lower bound, not a guarantee. Treat null as unknown, not zero.
- Rows are grouped by `status`, so a single flow appears on several rows. Sum
  across statuses before quoting a flow's total volume.
