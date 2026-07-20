---
doc_class: machine-object
object: supabase.reporting.v_daily_activity
kind: view
schema_hash: "sha256:93fefebe723a600426cb0ecce19d62404db664bb97e50ddc3fd6b7844790ed5e"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_daily_activity`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_daily_activity` |
| Kind | view |
| Schema hash | `sha256:93fefebe723a600426cb0ecce19d62404db664bb97e50ddc3fd6b7844790ed5e` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `day` | `date` | true | — | — | — |
| 2 | `jobs_created` | `bigint` | true | — | — | — |
| 3 | `cvs_tailored` | `bigint` | true | — | — | — |
| 4 | `exports_created` | `bigint` | true | — | — | — |
| 5 | `ai_runs_started` | `bigint` | true | — | — | — |

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
 SELECT d::date AS day,
    ( SELECT count(*) AS count
           FROM public.jobs j
          WHERE j.created_at::date = d.d::date) AS jobs_created,
    ( SELECT count(*) AS count
           FROM public.tailored_cvs t
          WHERE t.created_at::date = d.d::date) AS cvs_tailored,
    ( SELECT count(*) AS count
           FROM public.exports e
          WHERE e.created_at::date = d.d::date) AS exports_created,
    ( SELECT count(*) AS count
           FROM public.ai_runs a
          WHERE a.started_at::date = d.d::date) AS ai_runs_started
   FROM generate_series((( SELECT min(jobs.created_at)::date AS min
           FROM public.jobs))::timestamp with time zone, CURRENT_DATE::timestamp with time zone, '1 day'::interval) d(d);
```
