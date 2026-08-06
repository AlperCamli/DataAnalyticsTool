"""An in-process stand-in for Vault's AppRole + KV v2 HTTP surface.

Shared by the resolver's own tests and the JC-8 canary in
`test_sdk_service.py`, so the canary runs through the same code path a
real deployment does — the point of re-pointing it rather than writing a
second one beside it.

It is deliberately strict about the things that would let a broken
resolver pass: it refuses reads without a token it issued, it serves the
KV v2 envelope (`data.data`) rather than a flat map, and it records every
request so a test can assert what the runner did and did not send.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeResponse:
    status_code: int
    body: Any = None

    def json(self) -> Any:
        if self.body is None:
            raise ValueError("no JSON body")
        return self.body


@dataclass
class FakeVault:
    """`secrets` maps `"<mount>/<path>"` → `{field: value}`."""

    secrets: dict[str, dict[str, Any]] = field(default_factory=dict)
    role_id: str = "runner-role-id"
    secret_id: str = "runner-secret-id"
    lease_s: int = 60
    #: Tokens this vault has issued and still honours.
    issued: list[str] = field(default_factory=list)
    #: Every (method, url) it was asked for, in order.
    calls: list[tuple[str, str]] = field(default_factory=list)
    #: Bodies posted to it — what a leak would show up in.
    posted: list[Any] = field(default_factory=list)
    logins: int = 0
    #: Set to expire every token already issued (rotation / revocation).
    def revoke_all(self) -> None:
        self.issued.clear()

    def put(self, location: str, values: dict[str, Any]) -> None:
        """Write a secret, as the operator's `vault kv put` would."""
        self.secrets[location] = dict(values)

    # -- the requests.Session surface the resolver uses -------------------

    def post(self, url: str, json: Any = None, timeout: float | None = None):
        self.calls.append(("POST", url))
        self.posted.append(json)
        if not url.endswith("/auth/approle/login"):
            return FakeResponse(404)
        if json != {"role_id": self.role_id, "secret_id": self.secret_id}:
            return FakeResponse(400, {"errors": ["invalid role or secret id"]})
        self.logins += 1
        token = f"s.token-{self.logins}"
        self.issued.append(token)
        return FakeResponse(
            200,
            {"auth": {"client_token": token, "lease_duration": self.lease_s}},
        )

    def get(self, url: str, headers: dict | None = None, timeout: float | None = None):
        self.calls.append(("GET", url))
        if (headers or {}).get("X-Vault-Token") not in self.issued:
            return FakeResponse(403, {"errors": ["permission denied"]})
        # `/v1/<mount>/data/<path>` → the `<mount>/<path>` key above.
        _, _, tail = url.partition("/v1/")
        mount, _, rest = tail.partition("/")
        if not rest.startswith("data/"):
            return FakeResponse(404)
        location = f"{mount}/{rest[len('data/'):]}"
        if location not in self.secrets:
            return FakeResponse(404, {"errors": []})
        return FakeResponse(
            200, {"data": {"data": dict(self.secrets[location]), "metadata": {}}}
        )
