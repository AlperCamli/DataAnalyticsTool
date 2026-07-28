"""Preflight + env-contract tests for the Power BI leg (STOP-A tooling).

The operator command must fail loudly PER missing item with the exact
fill instruction (task 7.x step 2), and its failure text must never
carry secret material (JC-8). Network checks run against an injected
fake transport — the requests-backed default is exercised live by the
operator, which is the point of preflight.
"""

import pytest

from connectors.powerbi import reference as ref
from connectors.powerbi.config import load_powerbi_env
from connectors.powerbi.preflight import main, run_preflight
from connectors.sdk.errors import ConfigError

TENANT = "aaaabbbb-0000-cccc-1111-dddd2222eeee"
CLIENT = "00001111-aaaa-2222-bbbb-3333cccc4444"
SECRET = "canary-secret-value-A1bC2d"
WORKSPACE = "f089354e-8366-4e18-aea3-4cb4a3a50b48"


def write_env(tmp_path, **overrides):
    values = {
        "POWERBI_TENANT_ID": TENANT,
        "POWERBI_CLIENT_ID": CLIENT,
        "POWERBI_CLIENT_SECRET": SECRET,
        "POWERBI_WORKSPACE_ID": WORKSPACE,
    }
    values.update(overrides)
    path = tmp_path / "powerbi.env"
    path.write_text(
        "\n".join(f"{key}={value}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    return path


def env(tmp_path, **overrides):
    return load_powerbi_env(write_env(tmp_path, **overrides))


# --- env contract -----------------------------------------------------------


def test_missing_file_names_the_scaffold():
    with pytest.raises(ConfigError, match="does not exist"):
        load_powerbi_env("/nonexistent/powerbi.env")


def test_missing_keys_fail_together_with_fill_instructions(tmp_path):
    path = write_env(tmp_path, POWERBI_TENANT_ID="", POWERBI_CLIENT_SECRET="")
    with pytest.raises(ConfigError) as excinfo:
        load_powerbi_env(path)
    message = str(excinfo.value)
    # Both problems in ONE error — the operator fixes the file in one
    # pass — and each carries its exact fill instruction.
    assert "POWERBI_TENANT_ID is not set" in message
    assert "Tenant ID" in message
    assert "POWERBI_CLIENT_SECRET is not set" in message
    assert "secret VALUE" in message
    assert "POWERBI_CLIENT_ID" not in message.split("POWERBI_CLIENT_SECRET")[-1]


def test_non_uuid_id_is_flagged_with_its_instruction(tmp_path):
    path = write_env(tmp_path, POWERBI_CLIENT_ID="my-app-name")
    with pytest.raises(ConfigError, match="POWERBI_CLIENT_ID is set but is not a UUID"):
        load_powerbi_env(path)


def test_happy_path_loads(tmp_path):
    loaded = env(tmp_path)
    assert loaded.tenant_id == TENANT
    assert loaded.workspace_id == WORKSPACE


# --- preflight checks against a fake transport ------------------------------


class FakeMicrosoft:
    """Scriptable transport; asserts every URL it sees is pinned.

    `groups` may be a list (served every time) or a list of lists
    (served per successive groups.list call — models propagation)."""

    def __init__(self, *, token_status=200, groups=None, groups_status=200,
                 datasets_status=200, fabric_status=200, aadsts=""):
        self.token_status = token_status
        self.groups = groups if groups is not None else [{"id": WORKSPACE}]
        self.groups_status = groups_status
        self.datasets_status = datasets_status
        self.fabric_status = fabric_status
        self.aadsts = aadsts
        self.calls = []
        self.groups_served = 0

    def __call__(self, method, url, headers=None, form_data=None, timeout_s=30):
        name = ref.pinned_request(method, url)  # unpinned URL would raise here
        self.calls.append((name, method, url))
        if name == "token":
            if self.token_status == 200:
                return 200, {"access_token": "tok", "expires_in": 3599}
            return self.token_status, {"error_description": self.aadsts}
        if name == "groups.list":
            batch = self.groups
            if batch and isinstance(batch[0], list):
                batch = batch[min(self.groups_served, len(batch) - 1)]
            self.groups_served += 1
            return self.groups_status, {"value": batch}
        if name == "users.refresh_permissions":
            return 200, None
        if name == "datasets.list_in_group":
            return self.datasets_status, {"value": []}
        if name == "fabric.list_reports":
            return self.fabric_status, {"value": []}
        raise AssertionError(f"preflight called an unexpected endpoint {name}")


def no_sleep(_seconds):
    pass


def by_name(checks):
    return {check.name: check for check in checks}


def test_all_green(tmp_path):
    fake = FakeMicrosoft()
    checks = by_name(run_preflight(env(tmp_path), fake, sleeper=no_sleep))
    assert all(check.ok for check in checks.values()), checks
    assert set(checks) == {
        "token:powerbi", "token:fabric", "workspace-membership", "push-api", "fabric-api",
    }
    # Both scopes were requested — the Fabric deploy path has its own token.
    token_calls = [call for call in fake.calls if call[0] == "token"]
    assert len(token_calls) == 2


def test_bad_secret_fails_with_aadsts_hint_and_blocks_dependents(tmp_path):
    fake = FakeMicrosoft(
        token_status=401,
        aadsts="AADSTS7000215: Invalid client secret provided.",
    )
    checks = by_name(run_preflight(env(tmp_path), fake, sleeper=no_sleep))
    assert not checks["token:powerbi"].ok
    assert "POWERBI_CLIENT_SECRET is wrong or expired" in checks["token:powerbi"].message
    assert not checks["workspace-membership"].ok
    assert "blocked" in checks["workspace-membership"].message


def test_sp_not_workspace_member_names_the_fix(tmp_path):
    fake = FakeMicrosoft(groups=[{"id": "3d9b93c6-7b6d-4801-a491-1738910904fd"}])
    checks = by_name(run_preflight(env(tmp_path), fake, sleeper=no_sleep))
    assert not checks["workspace-membership"].ok
    assert "MEMBER" in checks["workspace-membership"].message
    assert "after a permissions refresh" in checks["workspace-membership"].message
    # The heal path ran: refresh was attempted, groups listed twice.
    assert [c[0] for c in fake.calls].count("users.refresh_permissions") == 1
    assert fake.groups_served == 2


def test_propagation_lag_heals_via_refresh_and_recheck(tmp_path):
    # First groups listing is empty (fresh grant not yet propagated);
    # after RefreshUserPermissions + the wait, the workspace appears.
    waits = []
    fake = FakeMicrosoft(groups=[[], [{"id": WORKSPACE}]])
    checks = by_name(run_preflight(env(tmp_path), fake, sleeper=waits.append))
    assert checks["workspace-membership"].ok
    assert checks["push-api"].ok
    assert waits == [120]
    assert [c[0] for c in fake.calls].count("users.refresh_permissions") == 1


def test_tenant_setting_refusal_names_the_setting(tmp_path):
    fake = FakeMicrosoft(groups_status=401)
    checks = by_name(run_preflight(env(tmp_path), fake, sleeper=no_sleep))
    assert not checks["workspace-membership"].ok
    assert "Allow service principals to use Power BI APIs" in checks["workspace-membership"].message
    assert not checks["push-api"].ok


def test_fabric_refusal_names_setting_and_licensing(tmp_path):
    fake = FakeMicrosoft(fabric_status=403)
    checks = by_name(run_preflight(env(tmp_path), fake, sleeper=no_sleep))
    assert not checks["fabric-api"].ok
    assert "Fabric" in checks["fabric-api"].message
    assert "licens" in checks["fabric-api"].message


def test_no_secret_material_in_any_message(tmp_path):
    # JC-8 at the operator surface — the AT-10 instinct applied to
    # preflight: whatever fails, the canary secret never prints.
    for fake in (
        FakeMicrosoft(),
        FakeMicrosoft(token_status=401, aadsts="AADSTS7000215: bad secret"),
        FakeMicrosoft(groups_status=403),
        FakeMicrosoft(fabric_status=500),
    ):
        for check in run_preflight(env(tmp_path), fake, sleeper=no_sleep):
            assert SECRET not in check.message


# --- the CLI wrapper --------------------------------------------------------


def test_main_offline_passes_on_complete_env(tmp_path, capsys):
    path = write_env(tmp_path)
    assert main(["--env", str(path), "--offline"]) == 0
    out = capsys.readouterr().out
    assert "all four POWERBI_* keys present" in out
    assert SECRET not in out


def test_main_reports_env_problems_and_exits_2(tmp_path, capsys):
    path = write_env(tmp_path, POWERBI_WORKSPACE_ID="")
    assert main(["--env", str(path), "--offline"]) == 2
    out = capsys.readouterr().out
    assert "POWERBI_WORKSPACE_ID is not set" in out
    assert "/groups/" in out  # the fill instruction, verbatim
