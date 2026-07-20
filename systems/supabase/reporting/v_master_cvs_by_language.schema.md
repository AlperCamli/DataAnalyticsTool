---
doc_class: machine-object
object: supabase.reporting.v_master_cvs_by_language
kind: view
schema_hash: "sha256:a79db79fd110a4c74212cf4ff0738568a509e37f588c776d694787f1efe2baf7"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_master_cvs_by_language`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_master_cvs_by_language` |
| Kind | view |
| Schema hash | `sha256:a79db79fd110a4c74212cf4ff0738568a509e37f588c776d694787f1efe2baf7` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `language` | `text` | true | — | — | Language of the master CV. |
| 2 | `source_type` | `text` | true | — | — | How the master CV originated, verbatim from the row. |
| 3 | `master_cv_count` | `bigint` | true | — | — | Active (not soft-deleted) master CVs. |
| 4 | `distinct_users` | `bigint` | true | — | — | Users holding at least one such master CV. |

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
 SELECT language,
    source_type,
    count(*) AS master_cv_count,
    count(DISTINCT user_id) AS distinct_users
   FROM public.master_cvs
  WHERE NOT is_deleted
  GROUP BY language, source_type;
```
