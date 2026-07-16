"""Credential-reference resolution (J-4) — the runner-side vault seam.

Job payloads carry references, never secrets. The runner resolves each
reference at `start` time under its own vault identity and holds the
value in memory only for the job's duration. This module defines the
reference interface every vault backend sits behind; CP-3a ships the
local-dev backend (ruling D1): process environment or an env file, both
addressed as

    env://NAME

Production vault schemes (`vault://…`, cloud-native URIs) land behind
the same `resolve(ref) -> str` seam later; nothing above this module
changes when they do.

Resolution failure is `auth_error` (non-retryable → re-auth flow) with
`detail.stage: "vault"`, distinguishing it from the source rejecting
valid credentials (§7). Error messages name the *reference*, never any
resolved value (JC-8).
"""

import os
import re
from pathlib import Path
from typing import Mapping, Protocol

from connectors.sdk.errors import AuthError

ENV_SCHEME = "env://"
_ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class VaultResolutionError(AuthError):
    """Reference did not resolve — the §7 vault-stage auth_error."""

    def __init__(self, message: str):
        super().__init__(message, detail={"stage": "vault"})


class CredentialResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


class EnvResolver:
    """Resolves `env://NAME` against a fixed mapping (never logs values)."""

    def __init__(self, mapping: Mapping[str, str], *, source: str = "process environment"):
        self._mapping = mapping
        self._source = source

    @classmethod
    def from_process_env(cls) -> "EnvResolver":
        return cls(os.environ)

    @classmethod
    def from_env_file(cls, path: str | Path) -> "EnvResolver":
        return cls(load_env_file(path), source=str(path))

    def resolve(self, ref: str) -> str:
        if not ref.startswith(ENV_SCHEME):
            raise VaultResolutionError(
                f"credential reference {ref!r}: unsupported scheme for this "
                f"resolver (expected {ENV_SCHEME}NAME)"
            )
        name = ref[len(ENV_SCHEME):]
        if not name or name != name.strip():
            raise VaultResolutionError(f"credential reference {ref!r}: malformed name")
        value = self._mapping.get(name)
        if value is None or value == "":
            raise VaultResolutionError(
                f"credential reference {ref!r}: {name} is not set in {self._source}"
            )
        return value


def load_env_file(path: str | Path) -> dict[str, str]:
    """Parse a KEY=VALUE env file (comments, blanks, optional `export`,
    optional single/double quotes around the value)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VaultResolutionError(f"cannot read env file {path}: {exc}") from exc
    values: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE.match(stripped)
        if not match:
            raise VaultResolutionError(
                f"env file {path}: line {lineno} is not KEY=VALUE"
            )
        key, value = match.group(1), match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values
