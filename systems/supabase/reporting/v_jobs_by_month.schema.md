---
doc_class: machine-object
object: supabase.reporting.v_jobs_by_month
kind: view
schema_hash: "sha256:139aa747a5499b9fd846f72f6b2215d977521874d4f31b6138b021cb57c4ee48"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_jobs_by_month`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_jobs_by_month` |
| Kind | view |
| Schema hash | `sha256:139aa747a5499b9fd846f72f6b2215d977521874d4f31b6138b021cb57c4ee48` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `month` | `date` | true | — | — | — |
| 2 | `job_count` | `bigint` | true | — | — | — |
| 3 | `distinct_users` | `bigint` | true | — | — | — |
| 4 | `applied_count` | `bigint` | true | — | — | — |

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
 SELECT date_trunc('month'::text, created_at)::date AS month,
    count(*) AS job_count,
    count(DISTINCT user_id) AS distinct_users,
    count(*) FILTER (WHERE applied_at IS NOT NULL) AS applied_count
   FROM public.jobs
  GROUP BY (date_trunc('month'::text, created_at)::date);
```
