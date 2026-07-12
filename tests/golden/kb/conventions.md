# Conventions

Bootstrapped skeleton (KB ruling K-7): completed at customer bootstrap
(task 1.6, playbook step 2) and human-owned from then on — the generator
never rewrites this file.

## System classes & dialects

_Completed at bootstrap: one entry per configured system (system class,
dialect, query surface)._

## Query guardrails per system

_Completed at bootstrap: execution policy per system (HLR §8 P2)._

## Trust-status behaviors

Machine docs (`status: machine`) carry introspected facts verbatim.
Statuses on human-owned docs (KB spec §5):

- `verified` — use freely.
- `draft` / `stale` — use, but warn the user explicitly.
- `contaminated` — refuse to build on it unless the user explicitly
  overrides, and say why (the broken reference is named in front-matter).

## Naming conventions

FQNs are `system.schema.name` (SQL) or `system.group.name` (API), always
backticked in doc bodies. Entities and metrics are referenced by path
(`entities/<entity>.md`), never by prose title.

## Quota notes for API sources

_Completed at bootstrap: per-source quota and freshness notes._

## Machine-readable guardrails

```yaml
# validate_sql per-system checks (MCP §6.6); populated at bootstrap.
```
