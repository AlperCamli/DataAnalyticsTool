# Setup

## Local demo

Create the Python environment and run the test suite:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -c constraints.txt -e '.[dev]'
.venv/bin/python -m pytest -q
```

Start the local stack and enqueue the credential-free demo jobs:

```sh
docker compose up -d --build
make stack-demo
```

The passwords and tokens in the base Compose file are localhost-only test
fixtures. Replace them for any shared or network-accessible deployment.

## External sources

Live mode is inert until explicitly configured. Create local files beneath
`.secrets/`; that directory is ignored by both Git and Docker build context.
Use the JSON shapes in `deploy/jobs/live-example/` as templates, replacing
every placeholder outside the repository.

Typical secret inputs include:

- `CL_INTROSPECT_DSN` — read-only catalog/introspection role;
- `CL_EXEC_DSN` — narrowly scoped governed execution role;
- `GOOGLE_SA_KEY_JSON` or a protected service-account key file;
- `POWERBI_CLIENT_SECRET`;
- deployment-specific GA4, GSC, Supabase, Looker Studio, and Power BI IDs.

The live Compose overlay expects:

- `.secrets/core-live/*.json` for deployment-specific job definitions;
- `.secrets/runner.env` for runner credential references;
- `.secrets/sync.env` for sync configuration;
- any provider key files referenced by those configurations.

Restrict secret files to the current user:

```sh
chmod 700 .secrets
find .secrets -type f -exec chmod 600 {} +
```

After configuration:

```sh
make stack-live
```

Do not copy live result captures into `results/`. Store operational evidence
in an access-controlled system and publish only sanitized fixtures.
