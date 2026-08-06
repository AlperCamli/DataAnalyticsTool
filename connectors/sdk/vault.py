"""Credential-reference resolution (J-4) — the runner-side vault seam.

Job payloads carry references, never secrets. The runner resolves each
reference at `start` time under its own vault identity and holds the
value in memory only for the job's duration. This module defines the
reference interface every backend sits behind:

    env://NAME                        local-dev backend (CP-3a, ruling D1)
    vault://<mount>/<path>#<field>    HashiCorp Vault KV v2 (A-4)

**`env://` is PILOT-ONLY.** It reads the runner's process environment or
an env file, which means the credential exists in plaintext somewhere on
the host — `.secrets/runner.env` on this machine. It is retained because
A-4's migration flips references one connection at a time and a runner
mid-flip must resolve both schemes, not because it is a supported
production posture. A deployment with no `env://` reference left has no
plaintext credential file left, which is A-4's whole point. Each use is
logged (by reference, never by value) so the remaining ones are visible
rather than assumed gone.

`vault://` is the supported one. The runner authenticates as itself
(AppRole) and reads KV v2; nothing above this module changed when it
landed, which is what the seam was for.

Resolution failure is `auth_error` (non-retryable → re-auth flow) with
`detail.stage: "vault"`, distinguishing it from the source rejecting
valid credentials (§7). Error messages name the *reference*, never any
resolved value, and never a response body — a vault response is made of
secrets (JC-8).
"""

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol
from urllib.parse import quote

import requests

from connectors.sdk.errors import AuthError

logger = logging.getLogger(__name__)

ENV_SCHEME = "env://"
VAULT_SCHEME = "vault://"
_ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


class VaultResolutionError(AuthError):
    """Reference did not resolve — the §7 vault-stage auth_error."""

    def __init__(self, message: str):
        super().__init__(message, detail={"stage": "vault"})


class CredentialResolver(Protocol):
    def resolve(self, ref: str) -> str: ...


class EnvResolver:
    """Resolves `env://NAME` against a fixed mapping (never logs values).

    PILOT-ONLY (see the module docstring): the value it returns came from
    a plaintext file or the process environment of this host.
    """

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


# --- HashiCorp Vault, KV v2 (A-4) --------------------------------------------


@dataclass(frozen=True)
class VaultRef:
    """A parsed `vault://<mount>/<path>#<field>` reference.

    The `/data/` segment KV v2's HTTP API requires is **not** part of the
    reference — the resolver inserts it. References stay readable, and a
    future engine-version change rewrites one line here instead of every
    connection row in the registry.
    """

    mount: str
    path: str
    field: str

    @property
    def read_path(self) -> str:
        """The KV v2 read path: `<mount>/data/<path>`."""
        segments = [quote(part, safe="") for part in self.path.split("/")]
        return f"{quote(self.mount, safe='')}/data/{'/'.join(segments)}"


def parse_vault_ref(ref: str) -> VaultRef:
    """`vault://secret/contextlayer/supabase#dsn` → VaultRef.

    Deliberately no version pin (`?version=3` and friends). A pinned
    reference is a rotation that silently does not take — write the new
    value into vault, watch nothing change, and go looking in the wrong
    place. That is the failure class this repo has paid for three times
    (D-84.2's family), and A-4's gate is precisely that a rotation *is*
    picked up on next resolution. Always-latest is the contract.
    """
    if not ref.startswith(VAULT_SCHEME):
        raise VaultResolutionError(
            f"credential reference {ref!r}: unsupported scheme for this "
            f"resolver (expected {VAULT_SCHEME}<mount>/<path>#<field>)"
        )
    body = ref[len(VAULT_SCHEME):]
    if "#" not in body:
        raise VaultResolutionError(
            f"credential reference {ref!r}: no #field — a KV v2 secret is a "
            "map, so the reference has to say which key it means"
        )
    location, _, field = body.partition("#")
    mount, _, path = location.partition("/")
    if not mount or not path or not field:
        raise VaultResolutionError(
            f"credential reference {ref!r}: expected "
            f"{VAULT_SCHEME}<mount>/<path>#<field>"
        )
    if any(part != part.strip() for part in (mount, path, field)) or "#" in field:
        raise VaultResolutionError(f"credential reference {ref!r}: malformed")
    return VaultRef(mount=mount, path=path.strip("/"), field=field)


@dataclass(frozen=True)
class VaultAuth:
    """How the runner proves it is itself.

    AppRole is the supported shape: the runner holds a role_id and a
    secret_id and exchanges them for a short-lived token. `token` is the
    dev-server path only — a root token in the environment is the same
    plaintext-credential problem A-4 exists to remove, one level up.
    """

    role_id: str | None = None
    secret_id: str | None = None
    token: str | None = None

    @property
    def is_approle(self) -> bool:
        return bool(self.role_id and self.secret_id)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "VaultAuth":
        env = os.environ if env is None else env
        auth = cls(
            role_id=env.get("VAULT_ROLE_ID") or None,
            secret_id=env.get("VAULT_SECRET_ID") or None,
            token=env.get("VAULT_TOKEN") or None,
        )
        if not auth.is_approle and not auth.token:
            raise VaultResolutionError(
                "vault identity is not configured: set VAULT_ROLE_ID + "
                "VAULT_SECRET_ID (AppRole), or VAULT_TOKEN for a dev server"
            )
        return auth


class VaultResolver:
    """Resolves `vault://<mount>/<path>#<field>` against HashiCorp Vault KV v2.

    The runner authenticates as *itself* (AppRole) and reads; no secret
    reaches it any other way and none is written back. The login token is
    cached in memory for its lease and re-acquired on expiry or on a 403,
    so a rotated secret_id recovers on the next job rather than needing a
    restart.

    Nothing in this class logs a response body. A vault read response is
    made entirely of credential material, so the JC-8 rule is not "scrub
    it" but "never touch it": errors name the reference and the HTTP
    status, and that is all they are allowed to know.
    """

    #: Re-login this many seconds before the lease actually ends, so a
    #: long job does not start with a token that expires mid-flight.
    RENEW_MARGIN_S = 30.0

    def __init__(
        self,
        addr: str,
        auth: VaultAuth,
        *,
        session: requests.Session | None = None,
        timeout_s: float = 10.0,
        approle_path: str = "approle",
        now: "callable[[], float] | None" = None,
    ):
        if not addr:
            raise VaultResolutionError("vault address is not configured (VAULT_ADDR)")
        self._addr = addr.rstrip("/")
        self._auth = auth
        self._session = session or requests.Session()
        self._timeout_s = timeout_s
        self._approle_path = approle_path
        self._now = now or time.monotonic
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, **kwargs
    ) -> "VaultResolver":
        env = os.environ if env is None else env
        return cls(env.get("VAULT_ADDR", ""), VaultAuth.from_env(env), **kwargs)

    # -- identity ---------------------------------------------------------

    def _login(self) -> tuple[str, float]:
        """AppRole login → (client_token, lease_seconds)."""
        if not self._auth.is_approle:
            # A static token has no lease we can see; treat it as valid
            # until something rejects it, which the 403 retry then handles.
            return self._auth.token or "", float("inf")
        url = f"{self._addr}/v1/auth/{self._approle_path}/login"
        try:
            response = self._session.post(
                url,
                json={"role_id": self._auth.role_id, "secret_id": self._auth.secret_id},
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            raise VaultResolutionError(
                f"vault unreachable at {self._addr}: {type(exc).__name__}"
            ) from None
        if response.status_code >= 400:
            # The runner's own identity was refused. Naming the status and
            # nothing else: the body of a failed login can echo the
            # secret_id that was sent.
            raise VaultResolutionError(
                f"vault AppRole login refused (HTTP {response.status_code}) — "
                "the runner's own VAULT_ROLE_ID/VAULT_SECRET_ID, not a "
                "connection credential"
            )
        try:
            auth = response.json()["auth"]
            return auth["client_token"], float(auth.get("lease_duration") or 0)
        except (ValueError, KeyError, TypeError):
            raise VaultResolutionError(
                "vault AppRole login returned no client_token"
            ) from None

    def _client_token(self, *, force: bool = False) -> str:
        with self._lock:
            if force:
                self._token = None
            if self._token is not None and self._now() < self._token_expires_at:
                return self._token
            token, lease_s = self._login()
            self._token = token
            self._token_expires_at = (
                float("inf")
                if lease_s == float("inf")
                else self._now() + max(lease_s - self.RENEW_MARGIN_S, 1.0)
            )
            return token

    # -- reads ------------------------------------------------------------

    def _read(self, ref: VaultRef, token: str) -> requests.Response:
        url = f"{self._addr}/v1/{ref.read_path}"
        try:
            return self._session.get(
                url, headers={"X-Vault-Token": token}, timeout=self._timeout_s
            )
        except requests.RequestException as exc:
            raise VaultResolutionError(
                f"vault unreachable at {self._addr}: {type(exc).__name__}"
            ) from None

    def resolve(self, ref: str) -> str:
        parsed = parse_vault_ref(ref)
        response = self._read(parsed, self._client_token())
        if response.status_code in (401, 403):
            # Expired or revoked token — re-login once, then believe it.
            response = self._read(parsed, self._client_token(force=True))

        if response.status_code == 404:
            raise VaultResolutionError(
                f"credential reference {ref!r}: no secret at "
                f"{parsed.mount}/{parsed.path} (or it is deleted)"
            )
        if response.status_code in (401, 403):
            raise VaultResolutionError(
                f"credential reference {ref!r}: denied by vault policy — the "
                "runner's identity may not read "
                f"{parsed.mount}/{parsed.path}"
            )
        if response.status_code >= 400:
            raise VaultResolutionError(
                f"credential reference {ref!r}: vault read failed "
                f"(HTTP {response.status_code})"
            )

        try:
            data = response.json()["data"]["data"]
        except (ValueError, KeyError, TypeError):
            raise VaultResolutionError(
                f"credential reference {ref!r}: vault response was not a KV v2 "
                "secret (is the mount KV version 2?)"
            ) from None
        if data is None:
            raise VaultResolutionError(
                f"credential reference {ref!r}: the secret at "
                f"{parsed.mount}/{parsed.path} has been deleted"
            )
        if not isinstance(data, dict) or parsed.field not in data:
            # Naming the *keys* would be a hint worth having, and is
            # exactly the hint that leaks a schema. The field name the
            # caller asked for is already in their hand; that is enough.
            raise VaultResolutionError(
                f"credential reference {ref!r}: the secret at "
                f"{parsed.mount}/{parsed.path} has no field {parsed.field!r}"
            )
        value = data[parsed.field]
        if value is None or value == "":
            raise VaultResolutionError(
                f"credential reference {ref!r}: field {parsed.field!r} is empty"
            )
        return value if isinstance(value, str) else str(value)


class SchemeRouter:
    """Dispatches a reference to the backend that owns its scheme.

    This is the seam doing its job, not a third resolver: A-4's migration
    flips references one connection at a time, so a runner mid-flip holds
    a registry with both `env://` and `vault://` rows and must resolve
    either. When the last `env://` reference is gone the env leg simply
    stops being reached, and `.secrets/runner.env` can go with it.
    """

    def __init__(self, backends: Mapping[str, CredentialResolver]):
        self._backends = dict(backends)

    def resolve(self, ref: str) -> str:
        for scheme, backend in self._backends.items():
            if ref.startswith(scheme):
                if scheme == ENV_SCHEME:
                    # The migration's own progress bar: every remaining
                    # plaintext-backed reference says so in the runner log,
                    # by name. Never the value (JC-8).
                    logger.warning(
                        "credential reference %s resolved through the PILOT-ONLY "
                        "env:// backend — this credential is still in plaintext "
                        "on this host (A-4)", ref,
                    )
                return backend.resolve(ref)
        raise VaultResolutionError(
            f"credential reference {ref!r}: no resolver for its scheme "
            f"(configured: {', '.join(sorted(self._backends)) or 'none'})"
        )


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
