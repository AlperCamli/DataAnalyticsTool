# Context Layer

Context Layer is a metadata and knowledge platform for governed analytics.
It captures normalized snapshots from data sources, renders a deterministic
git-based knowledge base, keeps that knowledge synchronized, and exposes it
to agent workflows through a server-enforced MCP surface.

The repository contains:

- connectors for PostgreSQL/Supabase, GA4, GSC, and static demo data;
- canonical snapshots, schema validation, deterministic rendering, and lineage;
- a TypeScript job service, queue, sync orchestrator, and MCP server;
- governed SQL execution and report-publishing adapters;
- conformance, integration, and end-to-end test suites.

## Quick start

Requirements: Python 3.12+, Node.js/npm, Docker, and Docker Compose.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -c constraints.txt -e '.[dev]'
.venv/bin/python -m pytest -q

docker compose up -d --build
make stack-demo
```

The Compose defaults are development fixtures bound to localhost. They are
not production credentials.

## Documentation

- [Setup](SETUP.md) — local demo and external-source configuration
- [Core service](core/README.md) — service layout, configuration, and tests
- [Specification index](specs/spec-index.md) — authoritative design documents
- [Operator guide](OPERATOR.md) — benchmark and operational workflows
- [Security policy](SECURITY.md) — reporting and credential-handling policy

## Data and credential policy

This public repository contains demo fixtures only. Keep credentials,
customer identifiers, analytics outputs, and live job definitions under
`.secrets/` or another external vault. Generated live-result directories
are ignored by Git. Never commit service-account keys, DSNs, access tokens,
or copied production evidence.
