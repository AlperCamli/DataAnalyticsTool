---
doc_class: machine-object
object: supabase.reporting.v_files_by_type
kind: view
schema_hash: "sha256:77d8d34973b23250d395f62b03acaea822380965f51458723d76e4a3f6cc6ad2"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_files_by_type`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_files_by_type` |
| Kind | view |
| Schema hash | `sha256:77d8d34973b23250d395f62b03acaea822380965f51458723d76e4a3f6cc6ad2` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `file_type` | `text` | true | — | — | Application-level file classification. |
| 2 | `mime_type` | `text` | true | — | — | MIME type recorded at upload. |
| 3 | `file_count` | `bigint` | true | — | — | Active (not soft-deleted) files. |
| 4 | `distinct_users` | `bigint` | true | — | — | Users owning at least one such file. |
| 5 | `total_bytes` | `numeric` | true | — | — | Sum of `size_bytes` across those files. |
| 6 | `avg_bytes` | `numeric` | true | — | — | Mean file size, rounded. |

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
 SELECT file_type,
    mime_type,
    count(*) AS file_count,
    count(DISTINCT user_id) AS distinct_users,
    sum(size_bytes) AS total_bytes,
    round(avg(size_bytes)) AS avg_bytes
   FROM public.files
  WHERE NOT is_deleted
  GROUP BY file_type, mime_type;
```
