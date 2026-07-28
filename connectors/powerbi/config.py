"""Power BI leg configuration — the .secrets/powerbi.env contract.

One file, four values, all operator-provisioned per ruling D-91.7 (the
customer-DBA pattern: Entra app + SP, workspace membership, tenant
settings are the customer side; we never do them, we verify them). The
loader fails loudly PER MISSING ITEM with the exact fill instruction —
`powerbi preflight` prints these same words, so the operator never has
to reverse-engineer what a key means from its name (JC-8: messages name
keys and references, never values).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from connectors.sdk.errors import ConfigError
from connectors.sdk.vault import load_env_file

DEFAULT_ENV_PATH = Path(".secrets/powerbi.env")

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

#: key -> (uuid_shaped, the exact fill instruction printed on absence).
REQUIRED_KEYS: dict[str, tuple[bool, str]] = {
    "POWERBI_TENANT_ID": (
        True,
        "Entra admin center → Overview → 'Tenant ID' (a UUID). This is the "
        "directory the app registration lives in.",
    ),
    "POWERBI_CLIENT_ID": (
        True,
        "Entra admin center → App registrations → your app → Overview → "
        "'Application (client) ID' (a UUID — NOT the object ID).",
    ),
    "POWERBI_CLIENT_SECRET": (
        False,
        "Entra admin center → App registrations → your app → Certificates & "
        "secrets → New client secret → copy the secret VALUE immediately "
        "(it is shown once). Paste the value, not the secret ID.",
    ),
    "POWERBI_WORKSPACE_ID": (
        True,
        "Power BI service → open the target workspace → the UUID in the "
        "browser URL after /groups/. The service principal must be a Member "
        "or Admin of this workspace.",
    ),
}


@dataclass(frozen=True)
class PowerBIEnv:
    tenant_id: str
    client_id: str
    client_secret: str
    workspace_id: str
    source: str


def load_powerbi_env(path: str | Path = DEFAULT_ENV_PATH) -> PowerBIEnv:
    """Load and validate .secrets/powerbi.env; ConfigError lists every
    missing/malformed key with its fill instruction (all at once — the
    operator fixes the file in one pass, not one error at a time)."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"{path} does not exist. Create it from the commented template "
            "(committed scaffold writes one) and fill the four POWERBI_* keys; "
            "the file is git-ignored and never leaves this machine (JC-8)."
        )
    values = load_env_file(path)
    problems: list[str] = []
    for key, (uuid_shaped, instruction) in REQUIRED_KEYS.items():
        value = values.get(key, "")
        if not value:
            problems.append(f"{key} is not set.\n    Fill: {instruction}")
        elif uuid_shaped and not _UUID.match(value):
            problems.append(
                f"{key} is set but is not a UUID.\n    Fill: {instruction}"
            )
    if problems:
        raise ConfigError(
            f"{path} is incomplete:\n\n- " + "\n- ".join(problems)
        )
    return PowerBIEnv(
        tenant_id=values["POWERBI_TENANT_ID"],
        client_id=values["POWERBI_CLIENT_ID"],
        client_secret=values["POWERBI_CLIENT_SECRET"],
        workspace_id=values["POWERBI_WORKSPACE_ID"],
        source=str(path),
    )
