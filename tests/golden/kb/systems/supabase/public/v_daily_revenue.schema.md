---
doc_class: machine-object
object: supabase.public.v_daily_revenue
kind: view
schema_hash: "sha256:9799300d96ba151b4d2418deed7eb9ce23483a3e88a3a82a469dc70c714956f3"
generated_at: 2026-07-11
source_mode: ddl-file
snapshot_version: "1"
status: machine
---

# `supabase.public.v_daily_revenue`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.v_daily_revenue` |
| Kind | view |
| Schema hash | `sha256:9799300d96ba151b4d2418deed7eb9ce23483a3e88a3a82a469dc70c714956f3` |

Paid revenue per calendar day. Used by the Looker Studio P&L page.

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `day` | `timestamp with time zone` | true | — | — | — |
| 2 | `revenue_cents` | `bigint` | true | — | — | — |
| 3 | `order_count` | `bigint` | true | — | — | — |

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
 SELECT date_trunc('day'::text, o.created_at) AS day,
    sum(o.total_cents) AS revenue_cents,
    count(*) AS order_count
   FROM orders o
  WHERE o.status = 'paid'::text
  GROUP BY (date_trunc('day'::text, o.created_at));
```
