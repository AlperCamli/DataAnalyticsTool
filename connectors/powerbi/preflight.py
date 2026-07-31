"""`powerbi preflight` — the operator admin command for STOP-A.

Verifies the D-91.7 customer-side provisioning end to end, failing
loudly per missing item with the exact fill instruction:

  1. env file complete (four POWERBI_* keys, per-key instructions)
  2. token acquisition — Power BI scope (client-credentials grant)
  3. token acquisition — Fabric scope (the PBIR deploy path's token)
  4. workspace membership — the SP sees the target workspace
  5. push-API reachability — datasets listing in the workspace
  6. Fabric-API reachability — report listing in the workspace
     (a licensing/tenant-setting refusal surfaces here, not at the
     first live deploy)

Run:  .venv/bin/python -m connectors.powerbi.preflight
      (or: make powerbi-preflight)

Every request is built by `pinned_endpoint` and re-checked by
`pinned_request` — the same AT-7 gate the publisher leg uses, so even
this diagnostic cannot emit an unpinned Microsoft call. Output names
keys, endpoints, and HTTP statuses; never secret values (JC-8).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable

from connectors.powerbi import reference as ref
from connectors.powerbi.config import DEFAULT_ENV_PATH, PowerBIEnv, load_powerbi_env
from connectors.sdk.errors import ConfigError

#: transport(method, url, headers, form_data, timeout_s) -> (status, json_body_or_none)
Transport = Callable[..., tuple[int, dict | None]]

_TIMEOUT_S = 30

#: AADSTS error codes worth translating to a fix, not just relaying.
_AADSTS_HINTS = {
    "AADSTS700016": "the POWERBI_CLIENT_ID is not an app in this tenant — re-check the Application (client) ID and the tenant.",
    "AADSTS7000215": "the POWERBI_CLIENT_SECRET is wrong or expired — mint a new secret and paste its VALUE (not the secret ID).",
    "AADSTS90002": "the POWERBI_TENANT_ID names no tenant — re-check the Tenant ID.",
    "AADSTS7000222": "the client secret has expired — mint a new one.",
    "AADSTS500011": "the resource scope was not found in the tenant — this is unexpected for the pinned Power BI/Fabric scopes; re-check the tenant.",
}


@dataclass
class Check:
    name: str
    ok: bool
    message: str
    #: An advisory does not gate STOP-A. It reports a posture the product
    #: cannot enforce and the operator may legitimately accept (R-5).
    advisory: bool = False


def _requests_transport(method: str, url: str, headers: dict | None = None,
                        form_data: dict | None = None, timeout_s: int = _TIMEOUT_S,
                        ) -> tuple[int, dict | None]:
    import requests  # imported here so offline/env-only runs never need it

    response = requests.request(method, url, headers=headers, data=form_data,
                                timeout=timeout_s)
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _acquire_token(env: PowerBIEnv, scope: str, transport: Transport) -> tuple[str | None, str]:
    method, url = ref.pinned_endpoint("token", tenantId=env.tenant_id)
    ref.pinned_request(method, url)
    status, body = transport(method, url, headers={"Content-Type": "application/x-www-form-urlencoded"},
                             form_data={
                                 "grant_type": "client_credentials",
                                 "client_id": env.client_id,
                                 "client_secret": env.client_secret,
                                 "scope": scope,
                             })
    if status == 200 and body and body.get("access_token"):
        return str(body["access_token"]), "token acquired"
    description = str((body or {}).get("error_description", "")).split("\n")[0]
    code = next((c for c in _AADSTS_HINTS if c in description), None)
    hint = f" → {_AADSTS_HINTS[code]}" if code else ""
    return None, (
        f"token request for scope {scope} failed (HTTP {status})"
        + (f": {description}" if description else "")
        + hint
    )


def _get(url_name: str, token: str, transport: Transport, **params: str) -> tuple[int, dict | None]:
    method, url = ref.pinned_endpoint(url_name, **params)
    ref.pinned_request(method, url)
    return transport(method, url, headers={"Authorization": f"Bearer {token}"})


#: A fresh workspace grant takes ~2 minutes to reach the API surface
#: (ref: users-refresh-permissions). On a membership miss, preflight
#: forces the refresh and re-checks once after this wait.
_PROPAGATION_WAIT_S = 120


def _visible_workspaces(token: str, transport: Transport) -> tuple[int, set[str]]:
    status, body = _get("groups.list", token, transport)
    ids = {str(g.get("id", "")).lower() for g in (body or {}).get("value", [])}
    return status, ids


def run_preflight(env: PowerBIEnv, transport: Transport | None = None,
                  sleeper: Callable[[float], None] | None = None) -> list[Check]:
    """The five network checks (tokens, membership, push API, Fabric
    API). Env-file validation happens before this in `main` — a caller
    holding a PowerBIEnv already passed it. `sleeper` is injectable so
    tests skip the real propagation wait."""
    transport = transport or _requests_transport
    if sleeper is None:
        import time

        sleeper = time.sleep
    checks: list[Check] = []

    pbi_token, message = _acquire_token(env, ref.PBI_SCOPE, transport)
    checks.append(Check("token:powerbi", pbi_token is not None, message))

    fabric_token, message = _acquire_token(env, ref.FABRIC_SCOPE, transport)
    checks.append(Check("token:fabric", fabric_token is not None, message))

    if pbi_token is None:
        skip = "blocked: no Power BI token (fix the token check first)"
        checks.append(Check("workspace-membership", False, skip))
        checks.append(Check("sp-scope", False, skip, advisory=True))
        checks.append(Check("push-api", False, skip))
    else:
        status, ids = _visible_workspaces(pbi_token, transport)
        if status != 200:
            checks.append(Check("workspace-membership", False, (
                f"GET /groups returned HTTP {status} — if 401/403, enable the tenant "
                "setting 'Allow service principals to use Power BI APIs' (Admin portal → "
                "Tenant settings → Developer settings) for the SP's security group, then wait "
                "a few minutes and re-run."
            )))
            checks.append(Check("sp-scope", False, "blocked: workspace listing failed",
                                advisory=True))
            checks.append(Check("push-api", False, "blocked: workspace listing failed"))
        else:
            member = env.workspace_id.lower() in ids
            refreshed = ""
            if not member:
                # The documented propagation lag: force the refresh
                # (best-effort — 429 means one already ran this hour),
                # wait the documented ~2 minutes, re-check once.
                refresh_status, _ = _get("users.refresh_permissions", pbi_token, transport)
                print(
                    f"      workspace not visible yet — RefreshUserPermissions "
                    f"(HTTP {refresh_status}); waiting {_PROPAGATION_WAIT_S}s for "
                    "propagation, then re-checking once…"
                )
                sleeper(_PROPAGATION_WAIT_S)
                status, ids = _visible_workspaces(pbi_token, transport)
                member = status == 200 and env.workspace_id.lower() in ids
                refreshed = " (after a permissions refresh + re-check)"
            checks.append(Check("workspace-membership", member, (
                "service principal is a member of the target workspace" if member else
                f"workspace {env.workspace_id} is not among the {len(ids)} workspace(s) the SP "
                f"can see{refreshed} — add the SP (or its security group) as a MEMBER of the "
                "workspace (workspace → Manage access), re-check POWERBI_WORKSPACE_ID, then "
                "re-run."
            )))
            # R-5 / RA-10: "member of the designated workspace(s) only".
            # The membership check above asserts the target IS among what
            # the SP can see; it says nothing about what else it can see.
            # Least privilege here was a human promise until this line —
            # the check RA-10 implies, stated rather than assumed.
            extra = sorted(ids - {env.workspace_id.lower()})
            checks.append(Check("sp-scope", not extra, (
                "service principal sees only the designated workspace (RA-10)" if not extra else
                f"RA-10 advisory: the SP can see {len(ids)} workspaces, {len(extra)} beyond the "
                f"designated one — {', '.join(extra[:5])}"
                f"{', …' if len(extra) > 5 else ''}. Delivered data is exec-role aggregates, so "
                "this does not gate the demo; but least privilege for this SP is a human promise "
                "until the extra memberships are removed (each workspace → Manage access) or "
                "accepted on the record."
            ), advisory=bool(extra)))
            status, _ = _get("datasets.list_in_group", pbi_token, transport,
                             groupId=env.workspace_id)
            checks.append(Check("push-api", status == 200, (
                "push/dataset API reachable in the workspace" if status == 200 else
                f"GET /groups/{{workspaceId}}/datasets returned HTTP {status} — the SP can see "
                "the workspace but not read its datasets; confirm the SP's role is Member or "
                "Admin (not Viewer)."
            )))

    if fabric_token is None:
        checks.append(Check("fabric-api", False, "blocked: no Fabric token (fix the token check first)"))
    else:
        status, _ = _get("fabric.list_reports", fabric_token, transport,
                         workspaceId=env.workspace_id)
        checks.append(Check("fabric-api", status == 200, (
            "Fabric report API reachable in the workspace" if status == 200 else
            f"GET /workspaces/{{workspaceId}}/reports returned HTTP {status} — if 401/403, "
            "the Fabric-side SP setting ('Service principals can call Fabric public APIs') or "
            "workspace role is missing; if the body names licensing, the workspace needs a "
            "license/capacity that permits report items (Fabric license types)."
        )))

    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="powerbi preflight",
        description="Verify the Power BI service-principal provisioning (STOP-A gate).",
    )
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH),
                        help=f"path to the env file (default: {DEFAULT_ENV_PATH})")
    parser.add_argument("--offline", action="store_true",
                        help="validate the env file only; no Microsoft calls")
    args = parser.parse_args(argv)

    print("powerbi preflight — D-91.7 provisioning verification\n")
    try:
        env = load_powerbi_env(args.env)
    except ConfigError as exc:
        print(f"FAIL  env-file        {exc}\n")
        print("Fix .secrets/powerbi.env per the instructions above, then re-run.")
        return 2
    print(f"ok    env-file        {env.source}: all four POWERBI_* keys present")

    if args.offline:
        print("\n(offline mode: skipping token, membership, and reachability checks)")
        return 0

    checks = run_preflight(env)
    print()
    for check in checks:
        marker = "ok  " if check.ok else ("warn" if check.advisory else "FAIL")
        print(f"{marker}  {check.name:<20} {check.message}")
    failed = [c for c in checks if not c.ok and not c.advisory]
    advisories = [c for c in checks if not c.ok and c.advisory]
    print()
    if failed:
        print(f"{len(failed)} of {len(checks)} checks failed. Fix the first failure and re-run;")
        print("later failures are often consequences of it.")
        return 3
    if advisories:
        # R-5: an advisory reports a posture the product cannot enforce.
        # It is loud and it does not block — the operator decides.
        print(f"{len(advisories)} advisory (not blocking): "
              f"{', '.join(c.name for c in advisories)}.")
    print("All checks passed. STOP-A clears on your word — the build resumes on it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
