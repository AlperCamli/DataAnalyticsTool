---
doc_class: machine-object
object: supabase.reporting.v_jobs_by_status
kind: view
schema_hash: "sha256:8ba1db1fd08c5a3bd5432b0e6e8d9f57d654a01b31ddf3f53c124f4036f9ba80"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_jobs_by_status`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_jobs_by_status` |
| Kind | view |
| Schema hash | `sha256:8ba1db1fd08c5a3bd5432b0e6e8d9f57d654a01b31ddf3f53c124f4036f9ba80` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `status` | `text` | true | — | — | — |
| 2 | `job_count` | `bigint` | true | — | — | — |
| 3 | `distinct_users` | `bigint` | true | — | — | — |
| 4 | `first_created` | `date` | true | — | — | — |
| 5 | `last_created` | `date` | true | — | — | — |

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
 SELECT status,
    count(*) AS job_count,
    count(DISTINCT user_id) AS distinct_users,
    min(created_at)::date AS first_created,
    max(created_at)::date AS last_created
   FROM public.jobs
  GROUP BY status;
```
