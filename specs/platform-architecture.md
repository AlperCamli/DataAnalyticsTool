# Context Layer — Platform Architecture & Tech Stack

Companion to `context-layer-v1-spec.md` (product spec) and `phase1-supabase-ga4-gsc-plan.md` (current customer). This document defines the extensible integration framework, the runtime topology, the tech stack, agent profiles, and the dashboard architecture.

---

## 1. Platform principles

**Minimal moving parts.** Self-hosted enterprise software is judged by what the customer's ops team must run and approve. Exactly two stateful dependencies: **git** (the KB — all knowledge, including agent profiles) and **Postgres** (all operational state — configs, sync runs, audit, benchmarks, and the job queue itself). No Redis, no Kafka, no external queue.

**Language-agnostic contracts, opinionated SDKs.** A connector is any process that emits valid snapshot JSON and speaks the job protocol. We ship a Python SDK; anyone can implement the contract in anything.

**Git is for knowledge, Postgres is for operations.** If a thing describes how the company's data works (docs, entities, metrics, conventions, agent profiles), it lives in git. If it describes what the system did (runs, logs, scores), it lives in Postgres.

**Enforcement server-side, convenience client-side.** Generated Claude Code configs are conveniences; the MCP server enforces role and profile permissions on every call regardless of client configuration.

## 2. Integration framework

### 2.1 Integration classes and capability interfaces

| Class | Examples | Capability interfaces implemented |
|---|---|---|
| Data source | Supabase/Postgres, MySQL, SQL Server, Snowflake, GA4, GSC | `MetadataProvider` (required), `QueryExecutor`, `UsageProvider` (optional) |
| Knowledge source | Google Drive, Confluence, wikis, docs repos | `KnowledgeProvider` — harvests existing documentation to seed human-owned docs via the enrich skill |
| Publish target | Looker Studio, Power BI, Tableau | `Publisher` with capability flags (create_report, template_link, sql_backing, cross_source) |
| Pipeline & transformation | dbt, Airbyte, Fivetran, custom ETL | `LineageProvider` (source → operation → target edges, column-level where derivable), often plus `MetadataProvider` for models |
| Identity | Customer IdP (OIDC) | Session/role resolution for MCP, gateway, and dashboard |
| Git provider | GitHub / GitLab / Azure DevOps | KB hosting, PR automation, CI webhooks |

Interface sketch (connector SDK):

```
MetadataProvider.snapshot(config) -> Snapshot            # normalized JSON, versioned schema
QueryExecutor.execute(request, identity) -> ResultSet    # SQL or API; guardrails applied by gateway
UsageProvider.usage(config, window) -> UsageStats
KnowledgeProvider.harvest(config) -> [SourceDocument]    # raw docs + provenance for enrichment
Publisher.capabilities() -> CapabilityFlags
Publisher.publish(artifact, target, identity) -> PublishResult
LineageProvider.lineage(config) -> LineageGraph          # edges: source → operation → target, column-level
```

SQL-derived lineage is additionally a *core* capability, not only connector-provided: the core parses view and model definitions captured in snapshots into column-level lineage edges. Deployments with no pipeline tooling (like the first demo) still get a full lineage graph, and the sync engine uses that same graph to propagate contamination flags downstream when sources change.

### 2.2 Connector lifecycle and reliability

Every connector is a versioned artifact with: fixture files and contract tests (snapshot validity, idempotency: same source state → byte-identical snapshot), declared rate-limit policy (the SDK provides backoff/retry/quota primitives — GA4 already exercises this), least-privilege credential references (never raw secrets; references into the customer's vault), and a health endpoint surfaced per connection in the dashboard. The snapshot schema evolves additively only; `snapshot_version` gates parsing. Sync jobs are idempotent and resumable; failures retry with backoff and dead-letter into the dashboard's health feed rather than silently dropping.

## 3. Runtime topology

```
┌───────────────────────── Customer environment ─────────────────────────┐
│                                                                        │
│  ┌────────────── core (TypeScript) ──────────────┐   ┌─ dashboard UI ─┐│
│  │  MCP server (streamable HTTP + OAuth/OIDC)    │◄──┤ React, config- ││
│  │  Execution gateway · Sync orchestrator        │   │ driven modules ││
│  │  Dashboard/API · Job queue (Postgres-backed)  │   └────────────────┘│
│  └───────┬────────────────────────────┬──────────┘                     │
│          │ job protocol               │                                │
│  ┌───────▼───────┐            ┌───────▼────────┐    ┌───────────────┐  │
│  │ Connector jobs │           │   Postgres     │    │  KB git repo  │  │
│  │ (Python SDK,   │           │ (ops state +   │    │ (docs, entities│  │
│  │  containerized)│           │  queue + audit)│    │  metrics,     │  │
│  └───────┬───────┘            └────────────────┘    │  profiles)    │  │
│          │                                          └───────▲───────┘  │
│   Sources: Supabase · GA4 · GSC · Drive · (future)          │ PRs      │
│   Secrets: customer vault    Identity: customer IdP ────────┘          │
└────────────────────────────────────────────────────────────────────────┘
            ▲ HTTPS (remote MCP, OAuth as the actual user)
   Claude Code — local machine or cloud workspace — same connection path
```

Deployment packaging: Docker Compose (small customers, current one) and Helm chart (enterprise K8s) from the same images. Versioned releases with DB migrations; offline/air-gap image bundles supported. A vendor fleet console is deferred; until then, upgrades are release-driven per deployment.

## 4. Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Core services | TypeScript / Node | MCP TypeScript SDK is the reference implementation; shared types end-to-end with the dashboard |
| MCP transport | Streamable HTTP + OAuth (customer OIDC) | One connection path for Claude Code local *and* cloud; per-user identity on every tool call |
| Connector SDK | Python | Richest driver/API ecosystem; the language of the data engineers who will extend it |
| Connector contract | JSON snapshot + job protocol | Language-agnostic; third-party connectors possible in any language |
| State | Postgres | Ops state, audit, benchmarks, and job queue (Postgres-backed queue — no extra broker) |
| Knowledge | Git (customer's server) | Docs, entities, metrics, conventions, agent profiles; PRs as the change mechanism |
| Dashboard | React + TypeScript | Served by core; config-driven modules; auth via the same OIDC session |
| Observability | OpenTelemetry + structured logs | Health endpoints per connector/connection; drift and freshness as first-class metrics |
| Packaging | Docker Compose / Helm | Matches customer size; air-gap bundles for strict environments |

## 5. Agent profiles (v1) — the portable unit

A profile is a complete, executable specification of a working agent, stored in the KB repo:

```yaml
# .contextlayer/profiles/sales-reporting.yaml
name: Sales Reporting Agent
description: Builds sales reports for business users
roles: [sales, sales-leadership]          # who may use it (OIDC groups)
skills: [report, enrich-readonly]          # shipped Claude Code skills included
tools:
  allow: [search_context, get_entity, get_table, get_metric, validate_sql,
          execute_sql:supabase, publish_report:looker-studio]
publish_targets: [looker-studio/sales-workspace]
context:
  claude_md_fragment: |
    Prefer certified metrics from metrics/. Warn on stale or contaminated docs.
limits: { row_cap: 50000, timeout_s: 60 }
```

Semantics: the dashboard provides CRUD over these files (writes land as git commits/PRs under the editing user's identity, per customer policy); the core compiles a profile into a one-line Claude Code setup (remote MCP config + skills bundle + CLAUDE.md fragment); and — the enforcement rule — the MCP server evaluates every tool call against (user's OIDC roles ∩ profile allowlist), so client-side config can never widen access. Because a profile fully specifies tools, skills, permissions, limits, and targets, the future headless runtime (roadmap: a scheduler service on the Claude Agent SDK executing profiles on triggers) requires no profile redesign — only an executor.

## 6. Dashboard architecture

One codebase, customized per customer through configuration, never forks:

```yaml
# .contextlayer/dashboard.yaml
branding: { name: "Acme Context Layer", logo: assets/acme.svg }
modules:
  connections: { enabled: true }
  kb_health:   { enabled: true }            # freshness/trust map, drift feed
  profiles:    { enabled: true, edit_roles: [data-team] }
  audit:       { enabled: true, view_roles: [data-team, security] }
  benchmarks:  { enabled: true }
role_views:                                  # which roles see which modules
  sales: [profiles]
  data-team: [connections, kb_health, profiles, audit, benchmarks]
```

Module registry v1: **Connections** (add/configure/test integrations, credential references, health), **KB Health** (estate freshness, stale/contaminated docs, drift feed, sync PR queue), **Agent Profiles** (§5 editor + one-click Claude Code setup export), **Audit** (queries, publishes, identities), **Benchmarks** (golden-suite scores over time, per KB version), **Lineage Explorer** (upstream/downstream graph per object, the operations applied on each edge, and trust-propagation overlays showing what a breaking change contaminates). Customer-specific panels are future extension points within the same registry — added by config, not code branches.

## 7. Build order impact

This platformization folds into the existing plan rather than replacing it: phase 1 tasks 1.1–1.4 now build against the connector SDK + contract from day one (same work, firmer skeleton); the MCP server work in phase 5 includes OAuth/streamable HTTP and profile enforcement; the dashboard becomes its own workstream after phase 5, starting with Connections and KB Health (they visualize state the pipeline already records), then Profiles. Nothing in phases 0–4 waits on the dashboard. Lineage derivation (the core's SQL parsing plus the `LineageProvider` contract) ships alongside phase 1, since the demo customer's view definitions exercise it from day one.
