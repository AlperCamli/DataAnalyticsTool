---
name: verify
description: How to verify a connector or snapshot-layer change end-to-end in this repo — drive the local CLI, validate the written snapshot, check C-2 byte-identity.
---

# Verifying changes in this repo

The runtime surface for connectors is the local CLI transport:

```bash
.venv/bin/python -m connectors.sdk.local MODULE:ATTR --config CONFIG.json --out OUT.json
# exit codes: 0 ok / 1 failed (no file, S-6) / 2 usage / 3 deferred (quota, J-5)
```

`MODULE:ATTR` names a `Connector` instance (`ATTR` defaults to
`connector`), e.g. `connectors.static_demo.connector`.

Validate whatever the CLI wrote with the 1.1 validator CLI:

```bash
.venv/bin/python -m snapshot.validate OUT.json   # exit 0 = valid, hashes checked
```

## API connectors without live credentials

GA4/GSC providers take an injectable `transport_factory` (anything with
`get(url, params) -> (status, headers, body)`). Write a small wrapper
module in a scratch dir that wraps the real provider with recorded
bodies from `tests/data/<connector>/`, then point the CLI at it with
`PYTHONPATH=<scratchdir>` — everything except the network (manifest,
config validation, emission gate, atomic write, exit codes) runs for
real. Live paths are env-gated pytest markers (`ga4_live`, `gsc_live`),
not something to drive without customer credentials.

## Flows worth driving

- Success → exit 0, then `snapshot.validate` the file, then rerun and
  compare bodies minus `captured_at` (C-2 at the surface).
- A taxonomy failure (bad config, unverified/denied recording) →
  exit 1 **and the --out file must not exist** (S-6).
- Persistent 429 recording → exit 3 with `retry_after_s` printed.
  Gotcha: default `sleep` is `time.sleep`, so the CLI really sleeps
  through the backoff schedule (~15 s with 4 retries) — expected.
- Postgres ddl-file mode needs a running Docker daemon (spins ephemeral
  containers); without it only live mode / recorded paths are drivable.
