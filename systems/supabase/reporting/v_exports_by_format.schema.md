---
doc_class: machine-object
object: supabase.reporting.v_exports_by_format
kind: view
schema_hash: "sha256:23ebec8a64c7bd850eebd3897530e3f5bcba383827dae25329453280bd1d4076"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_exports_by_format`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_exports_by_format` |
| Kind | view |
| Schema hash | `sha256:23ebec8a64c7bd850eebd3897530e3f5bcba383827dae25329453280bd1d4076` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `format` | `text` | true | — | — | Export output format (e.g. pdf, docx). |
| 2 | `status` | `text` | true | — | — | Export outcome status. |
| 3 | `export_count` | `bigint` | true | — | — | Exports matching this format/status. |
| 4 | `distinct_users` | `bigint` | true | — | — | Users with at least one such export. |

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
 SELECT format,
    status,
    count(*) AS export_count,
    count(DISTINCT user_id) AS distinct_users
   FROM public.exports
  GROUP BY format, status;
```
