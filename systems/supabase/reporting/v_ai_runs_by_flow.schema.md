---
doc_class: machine-object
object: supabase.reporting.v_ai_runs_by_flow
kind: view
schema_hash: "sha256:decb62fc93c17415b1901bbbdabe0f4676c767f640007addbb7f5aad904e1ece"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_ai_runs_by_flow`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_ai_runs_by_flow` |
| Kind | view |
| Schema hash | `sha256:decb62fc93c17415b1901bbbdabe0f4676c767f640007addbb7f5aad904e1ece` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `flow_type` | `text` | true | — | — | Logical AI flow executed; the same enum as `public.ai_runs.flow_type`. |
| 2 | `provider` | `text` | true | — | — | AI provider that served the run. |
| 3 | `model_name` | `text` | true | — | — | Specific model used. |
| 4 | `status` | `text` | true | — | — | Terminal status of the run (`pending` \| `completed` \| `failed`). |
| 5 | `run_count` | `bigint` | true | — | — | Runs matching this combination. |
| 6 | `distinct_users` | `bigint` | true | — | — | Users who triggered at least one such run. |
| 7 | `input_tokens` | `bigint` | true | — | — | Sum of input tokens; null-valued rows contribute nothing. |
| 8 | `output_tokens` | `bigint` | true | — | — | Sum of output tokens. |
| 9 | `total_tokens` | `bigint` | true | — | — | Sum of billed tokens — the figure to use for cost. |
| 10 | `avg_seconds` | `numeric` | true | — | — | Mean wall-clock seconds from `started_at` to `completed_at`, to 2dp. |

## Keys & indexes

Primary key: —

Foreign keys: —

Unique constraints: —

Indexes: —

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—

## View definition

```sql
 SELECT flow_type,
    provider,
    model_name,
    status,
    count(*) AS run_count,
    count(DISTINCT user_id) AS distinct_users,
    sum(input_tokens) AS input_tokens,
    sum(output_tokens) AS output_tokens,
    sum(total_tokens) AS total_tokens,
    round(avg(EXTRACT(epoch FROM completed_at - started_at)), 2) AS avg_seconds
   FROM public.ai_runs
  GROUP BY flow_type, provider, model_name, status;
```
