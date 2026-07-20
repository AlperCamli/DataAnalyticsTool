---
doc_class: human-object
object: supabase.reporting.v_imports_by_parser
written_against_schema_hash: "sha256:cb1b281c8f54924d118cd6494afcf2ab872b107d591c9adbc9011915dc8c78f4"
status: draft
last_verified: null
purpose: "CV import volume by parser and outcome — the reliability view for document ingestion."
column_purposes:
  parser_name: "Parser that handled the import."
  status: "Import outcome status."
  import_count: "Imports matching this parser/status."
  distinct_users: "Users with at least one such import."
sources:
  - "platform: deploy/reporting-views.sql (view definition, CP-6/M2)"
  - "machine doc: supabase.reporting.v_imports_by_parser"
  - "human doc: supabase.public.imports"
depends_on:
  - supabase.public.imports
contamination: null
---

# `supabase.reporting.v_imports_by_parser`

## Grain

One row per (parser_name, status) pair observed.

## Reporting notes

- Parser reliability: failure share per parser is the ingestion-quality
  metric, and imports are a first-run experience, so failures here cost more
  than their volume suggests.

## Warnings

- **These are aggregate views over row-level-security-protected tables.** The
  base tables (`public.*`) enforce per-user RLS, so the execution role reads
  **zero rows** from them directly. These views answer anyway because a view
  evaluates RLS as its *owner*, and they are owned by a role that bypasses it.
  That is a deliberate, narrow opening — and it is why every column here is an
  aggregate or a non-identifying dimension. Do not expect to drill from these
  numbers to a person: no view exposes `user_id`, an email, a name, or any free
  text a user wrote.
- **Small counts can still identify.** The estate is ~24 users. A group of size
  1–2 is potentially personal even though no column names anyone; treat such
  cells as sensitive rather than reportable.
- Grouped by status; sum across statuses for a parser's total.
- A parser with low volume and high failure may still matter — check
  `distinct_users`, since a rare format failing for every user who has it is a
  worse problem than the raw count implies.
