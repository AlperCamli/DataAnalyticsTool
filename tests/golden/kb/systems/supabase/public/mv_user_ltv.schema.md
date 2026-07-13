---
doc_class: machine-object
object: supabase.public.mv_user_ltv
kind: materialized_view
schema_hash: "sha256:51f42f2bd4cfdf410cb428545114b33f017bed8ba3564286b6de1175d31dec42"
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---

# `supabase.public.mv_user_ltv`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.mv_user_ltv` |
| Kind | materialized_view |
| Schema hash | `sha256:51f42f2bd4cfdf410cb428545114b33f017bed8ba3564286b6de1175d31dec42` |

Lifetime value per user; refreshed nightly by pg_cron.

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `user_id` | `uuid` | true | — | — | — |
| 2 | `ltv_cents` | `bigint` | true | — | — | — |
| 3 | `first_order_at` | `timestamp with time zone` | true | — | — | — |
| 4 | `last_order_at` | `timestamp with time zone` | true | — | — | — |

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
 SELECT o.user_id,
    sum(o.total_cents) AS ltv_cents,
    min(o.created_at) AS first_order_at,
    max(o.created_at) AS last_order_at
   FROM orders o
  WHERE o.status = 'paid'::text
  GROUP BY o.user_id;
```
