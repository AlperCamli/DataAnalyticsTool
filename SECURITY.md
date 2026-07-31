# Security Policy

## Reporting a vulnerability

Please use GitHub's private vulnerability-reporting feature for this
repository. Do not disclose exploitable details, credentials, customer data,
or production identifiers in a public issue. If private reporting is not
available, contact the repository owner through their GitHub profile before
sharing technical details.

## Credential handling

This repository must contain credential references only. Keep DSNs, API keys,
OAuth secrets, service-account JSON, signing keys, customer identifiers, and
live analytics results outside version control under `.secrets/` or an
external secret manager.

The values committed in development Compose and test fixtures are intentionally
local and must not be reused in a shared or production environment.

If a real credential is committed, revoke or rotate it immediately, remove it
from every reachable Git revision, and verify the rewritten repository from a
fresh clone before considering the incident closed.

## Supported version

Security fixes are applied to the current `main` branch.
