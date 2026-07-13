---
doc_class: machine-object
object: supabase.public.cv_block_revisions
kind: table
schema_hash: "sha256:3a1278bd5ecfd1421d8e528690c056db43cf2a1beefe7af00752ac1858e98415"
generated_at: 2026-07-12
source_mode: live
snapshot_version: "1"
status: machine
---

# `supabase.public.cv_block_revisions`

## Identity

| Fact | Value |
|---|---|
| Object | `supabase.public.cv_block_revisions` |
| Kind | table |
| Schema hash | `sha256:3a1278bd5ecfd1421d8e528690c056db43cf2a1beefe7af00752ac1858e98415` |

## Columns

| # | Column | Type | Nullable | Default | Description | Purpose |
|---|---|---|---|---|---|---|
| 1 | `id` | `uuid` | false | `gen_random_uuid()` | — | Internal revision id. |
| 2 | `user_id` | `uuid` | false | — | — | Owning user whose CV this revision belongs to (FK to users.id). |
| 3 | `cv_kind` | `text` | false | — | — | Which CV kind this revision is scoped to; enum in body. |
| 4 | `master_cv_id` | `uuid` | true | — | — | Master CV the revision belongs to when cv_kind='master' (FK). |
| 5 | `tailored_cv_id` | `uuid` | true | — | — | Tailored CV the revision belongs to when cv_kind='tailored' (FK). |
| 6 | `block_id` | `text` | false | — | — | Identifier of the CV block this revision captures. |
| 7 | `block_type` | `text` | false | — | — | Type of the block at revision time (e.g. experience, education). |
| 8 | `revision_number` | `integer` | false | — | — | Monotonic revision number per (cv, block_id); positive. |
| 9 | `content_snapshot` | `jsonb` | false | — | — | Full block content snapshot as JSONB; structure in body. |
| 10 | `change_source` | `text` | false | — | — | What produced the revision; enum in body. |
| 11 | `ai_suggestion_id` | `uuid` | true | — | — | AI suggestion that originated this revision when change_source='ai' (FK). |
| 12 | `created_at` | `timestamp with time zone` | false | `now()` | — | When the revision was recorded. |
| 13 | `created_by_user_id` | `uuid` | true | — | — | User who triggered the revision, when applicable (FK to users.id). |

## Keys & indexes

Primary key: `id`

Foreign keys:

| Columns | References | Referenced columns |
|---|---|---|
| `ai_suggestion_id` | [`public.ai_suggestions`](ai_suggestions.schema.md) | `id` |
| `created_by_user_id` | [`public.users`](users.schema.md) | `id` |
| `master_cv_id` | [`public.master_cvs`](master_cvs.schema.md) | `id` |
| `tailored_cv_id` | [`public.tailored_cvs`](tailored_cvs.schema.md) | `id` |
| `user_id` | [`public.users`](users.schema.md) | `id` |

Unique constraints: —

Indexes:

- `CREATE INDEX cv_block_revisions_master_block_idx ON public.cv_block_revisions USING btree (master_cv_id, block_id, revision_number DESC) WHERE ((cv_kind = 'master'::text) AND (master_cv_id IS NOT NULL))`
- `CREATE INDEX cv_block_revisions_tailored_block_idx ON public.cv_block_revisions USING btree (tailored_cv_id, block_id, revision_number DESC) WHERE ((cv_kind = 'tailored'::text) AND (tailored_cv_id IS NOT NULL))`
- `CREATE INDEX cv_block_revisions_user_created_at_idx ON public.cv_block_revisions USING btree (user_id, created_at DESC)`
- `CREATE UNIQUE INDEX cv_block_revisions_master_unique_revision_idx ON public.cv_block_revisions USING btree (master_cv_id, block_id, revision_number) WHERE ((cv_kind = 'master'::text) AND (master_cv_id IS NOT NULL))`
- `CREATE UNIQUE INDEX cv_block_revisions_tailored_unique_revision_idx ON public.cv_block_revisions USING btree (tailored_cv_id, block_id, revision_number) WHERE ((cv_kind = 'tailored'::text) AND (tailored_cv_id IS NOT NULL))`

## Row estimate & freshness

Row estimate: —

Freshness: facts reflect the snapshot recorded in `generated_at` (front-matter).

## Referenced-by

—
