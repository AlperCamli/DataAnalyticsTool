---
doc_class: machine-object
object: supabase.reporting.v_cv_production
kind: view
schema_hash: "sha256:228d079f208abe02ea559884b36e89a3a330abeaca3176a1fe215333344c08bd"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_cv_production`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_cv_production` |
| Kind | view |
| Schema hash | `sha256:228d079f208abe02ea559884b36e89a3a330abeaca3176a1fe215333344c08bd` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `month` | `date` | true | — | — | Calendar month the tailored CV was created. |
| 2 | `language` | `text` | true | — | — | Language of the tailored CV, verbatim from the row. |
| 3 | `tailored_cv_count` | `bigint` | true | — | — | Tailored CVs created in that month/language, including soft-deleted ones. |
| 4 | `distinct_users` | `bigint` | true | — | — | Users who created at least one tailored CV in that month/language. |
| 5 | `deleted_count` | `bigint` | true | — | — | How many of those are now flagged `is_deleted`. |

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
    language,
    count(*) AS tailored_cv_count,
    count(DISTINCT user_id) AS distinct_users,
    count(*) FILTER (WHERE is_deleted) AS deleted_count
   FROM public.tailored_cvs
  GROUP BY (date_trunc('month'::text, created_at)::date), language;
```
