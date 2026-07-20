---
doc_class: machine-object
object: supabase.reporting.v_imports_by_parser
kind: view
schema_hash: "sha256:cb1b281c8f54924d118cd6494afcf2ab872b107d591c9adbc9011915dc8c78f4"
generated_at: 2026-07-20
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.reporting.v_imports_by_parser`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.reporting.v_imports_by_parser` |
| Kind | view |
| Schema hash | `sha256:cb1b281c8f54924d118cd6494afcf2ab872b107d591c9adbc9011915dc8c78f4` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `parser_name` | `text` | true | — | — | — |
| 2 | `status` | `text` | true | — | — | — |
| 3 | `import_count` | `bigint` | true | — | — | — |
| 4 | `distinct_users` | `bigint` | true | — | — | — |

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
 SELECT parser_name,
    status,
    count(*) AS import_count,
    count(DISTINCT user_id) AS distinct_users
   FROM public.imports
  GROUP BY parser_name, status;
```
