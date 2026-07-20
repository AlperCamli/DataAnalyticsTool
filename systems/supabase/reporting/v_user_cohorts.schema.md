---
doc_class: machine-object
object: supabase.reporting.v_user_cohorts
kind: view
schema_hash: "sha256:fd10b9487cd3fb8b73aed002d33d75bf007dcb08ae09d2eb89023d3e223273d1"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_user_cohorts`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_user_cohorts` |
| Kind | view |
| Schema hash | `sha256:fd10b9487cd3fb8b73aed002d33d75bf007dcb08ae09d2eb89023d3e223273d1` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `signup_month` | `date` | true | — | — | Calendar month the user record was created. |
| 2 | `locale` | `text` | true | — | — | User's locale setting. |
| 3 | `default_cv_language` | `text` | true | — | — | User's default CV language. |
| 4 | `user_count` | `bigint` | true | — | — | Users in this cohort. |
| 5 | `onboarded_count` | `bigint` | true | — | — | How many completed onboarding. |

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
 SELECT date_trunc('month'::text, created_at)::date AS signup_month,
    locale,
    default_cv_language,
    count(*) AS user_count,
    count(*) FILTER (WHERE onboarding_completed) AS onboarded_count
   FROM public.users
  GROUP BY (date_trunc('month'::text, created_at)::date), locale, default_cv_language;
```
