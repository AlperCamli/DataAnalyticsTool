---
doc_class: machine-object
object: supabase.reporting.v_subscriptions_by_plan
kind: view
schema_hash: "sha256:1abbef8441881fd2ac21600b36be45426643c2b38c1609fe6d31fb9da753b853"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_subscriptions_by_plan`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_subscriptions_by_plan` |
| Kind | view |
| Schema hash | `sha256:1abbef8441881fd2ac21600b36be45426643c2b38c1609fe6d31fb9da753b853` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `plan_code` | `text` | true | — | — | — |
| 2 | `status` | `text` | true | — | — | — |
| 3 | `subscription_count` | `bigint` | true | — | — | — |
| 4 | `cancelling_count` | `bigint` | true | — | — | — |

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
 SELECT plan_code,
    status,
    count(*) AS subscription_count,
    count(*) FILTER (WHERE cancel_at_period_end) AS cancelling_count
   FROM public.subscriptions
  GROUP BY plan_code, status;
```
