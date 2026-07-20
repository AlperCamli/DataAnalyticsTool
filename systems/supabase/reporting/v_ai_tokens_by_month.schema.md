---
doc_class: machine-object
object: supabase.reporting.v_ai_tokens_by_month
kind: view
schema_hash: "sha256:0bd767c407e3273723c4e62a1f96d03fe0d846ba5c8b211ab519010d00535706"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_ai_tokens_by_month`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_ai_tokens_by_month` |
| Kind | view |
| Schema hash | `sha256:0bd767c407e3273723c4e62a1f96d03fe0d846ba5c8b211ab519010d00535706` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `month` | `date` | true | — | — | Calendar month of `started_at`. |
| 2 | `provider` | `text` | true | — | — | AI provider that served the runs. |
| 3 | `total_tokens` | `bigint` | true | — | — | Sum of billed tokens for the month/provider. |
| 4 | `run_count` | `bigint` | true | — | — | Runs started in that month. |
| 5 | `non_completed_count` | `bigint` | true | — | — | Runs whose status is anything other than `completed`. |

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
 SELECT date_trunc('month'::text, started_at)::date AS month,
    provider,
    sum(total_tokens) AS total_tokens,
    count(*) AS run_count,
    count(*) FILTER (WHERE status <> 'completed'::text) AS non_completed_count
   FROM public.ai_runs
  GROUP BY (date_trunc('month'::text, started_at)::date), provider;
```
