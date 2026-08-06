"""Credential-reference resolution (connectors/sdk/vault.py, J-4).

Resolution failure must be the §7 vault-stage auth_error, and no error
message may carry resolved values — only references.

Two backends behind one seam: `env://` (pilot-only, plaintext on the
host) and `vault://` (HashiCorp Vault KV v2, A-4). The vault half is
exercised against `tests/fake_vault.py` rather than a live server, so
these run everywhere; the live path is proved by the pilot migration.
"""

import logging

import pytest

from connectors.sdk.vault import (
    ENV_SCHEME,
    VAULT_SCHEME,
    EnvResolver,
    SchemeRouter,
    VaultAuth,
    VaultResolutionError,
    VaultResolver,
    load_env_file,
    parse_vault_ref,
)
from tests.fake_vault import FakeVault


def make_vault(secrets=None, **kwargs):
    """A resolver wired to a fake vault, plus the vault itself."""
    vault = FakeVault(**kwargs)
    for location, values in (secrets or {}).items():
        vault.put(location, values)
    resolver = VaultResolver(
        "https://vault.invalid",
        VaultAuth(role_id=vault.role_id, secret_id=vault.secret_id),
        session=vault,
    )
    return resolver, vault


def test_process_env_resolution(monkeypatch):
    monkeypatch.setenv("CL_TEST_SECRET", "s3cret-value")
    assert EnvResolver.from_process_env().resolve("env://CL_TEST_SECRET") == "s3cret-value"


def test_env_file_resolution(tmp_path):
    env_file = tmp_path / "cl.env"
    env_file.write_text(
        "# local dev vault\n"
        "\n"
        "PLAIN=value1\n"
        "export EXPORTED=value2\n"
        'DOUBLE="quoted value"\n'
        "SINGLE='single quoted'\n"
        "TRAILING=  spaced  \n",
        encoding="utf-8",
    )
    resolver = EnvResolver.from_env_file(env_file)
    assert resolver.resolve("env://PLAIN") == "value1"
    assert resolver.resolve("env://EXPORTED") == "value2"
    assert resolver.resolve("env://DOUBLE") == "quoted value"
    assert resolver.resolve("env://SINGLE") == "single quoted"
    assert resolver.resolve("env://TRAILING") == "spaced"


def test_missing_name_is_vault_stage_auth_error(tmp_path):
    env_file = tmp_path / "cl.env"
    env_file.write_text("OTHER=x\n", encoding="utf-8")
    resolver = EnvResolver.from_env_file(env_file)
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("env://MISSING")
    assert excinfo.value.code == "auth_error"
    assert excinfo.value.retryable is False
    assert excinfo.value.detail == {"stage": "vault"}


def test_unsupported_scheme_rejected():
    with pytest.raises(VaultResolutionError):
        EnvResolver.from_process_env().resolve("vault://kv/data/dsn")


def test_malformed_env_file_rejected(tmp_path):
    env_file = tmp_path / "cl.env"
    env_file.write_text("NOT A LINE\n", encoding="utf-8")
    with pytest.raises(VaultResolutionError):
        load_env_file(env_file)


def test_empty_value_treated_as_unset(monkeypatch):
    monkeypatch.setenv("CL_EMPTY", "")
    with pytest.raises(VaultResolutionError):
        EnvResolver.from_process_env().resolve("env://CL_EMPTY")


def test_error_messages_never_carry_values(tmp_path):
    """JC-8 discipline: references in errors, never resolved material."""
    env_file = tmp_path / "cl.env"
    env_file.write_text("PRESENT=super-secret-canary\n", encoding="utf-8")
    resolver = EnvResolver.from_env_file(env_file)
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("env://ABSENT")
    assert "super-secret-canary" not in str(excinfo.value)


# --- vault:// reference parsing ---------------------------------------------


def test_reference_parses_into_mount_path_and_field():
    ref = parse_vault_ref("vault://secret/contextlayer/supabase#dsn")
    assert (ref.mount, ref.path, ref.field) == ("secret", "contextlayer/supabase", "dsn")
    # The `/data/` segment KV v2 requires is inserted here, not carried in
    # the reference — so references stay readable and an engine-version
    # change rewrites one line instead of every registry row.
    assert ref.read_path == "secret/data/contextlayer/supabase"


@pytest.mark.parametrize(
    "ref",
    [
        "vault://secret/contextlayer/supabase",  # no #field
        "vault://secret#dsn",                     # no path
        "vault:///contextlayer#dsn",              # no mount
        "vault://secret/contextlayer#",           # empty field
        "env://CL_EXEC_DSN",                      # wrong scheme for this parser
    ],
)
def test_malformed_references_are_vault_stage_auth_errors(ref):
    with pytest.raises(VaultResolutionError) as excinfo:
        parse_vault_ref(ref)
    assert excinfo.value.code == "auth_error"
    assert excinfo.value.detail == {"stage": "vault"}


# --- vault:// resolution (KV v2 + AppRole) ----------------------------------


def test_resolves_a_kv_v2_field_under_its_own_approle_identity():
    resolver, vault = make_vault({"secret/contextlayer/pilot": {"dsn": "postgres://x"}})
    assert resolver.resolve("vault://secret/contextlayer/pilot#dsn") == "postgres://x"
    assert vault.logins == 1
    assert vault.calls[0][0] == "POST"  # login before read
    assert vault.calls[1] == ("GET", "https://vault.invalid/v1/secret/data/contextlayer/pilot")


def test_the_login_token_is_reused_across_resolutions():
    """One identity exchange per lease, not one per credential — a job
    with three credentials should not log in three times."""
    resolver, vault = make_vault(
        {"secret/a": {"k": "1"}, "secret/b": {"k": "2"}, "secret/c": {"k": "3"}}
    )
    for name in "abc":
        resolver.resolve(f"vault://secret/{name}#k")
    assert vault.logins == 1


def test_an_expired_lease_re_logs_in_rather_than_failing():
    """The runner is long-lived; its token is not. A lease that ran out
    between jobs must cost a login, not a job."""
    clock = [0.0]
    vault = FakeVault(lease_s=60)
    vault.put("secret/a", {"k": "v"})
    resolver = VaultResolver(
        "https://vault.invalid",
        VaultAuth(role_id=vault.role_id, secret_id=vault.secret_id),
        session=vault,
        now=lambda: clock[0],
    )
    assert resolver.resolve("vault://secret/a#k") == "v"
    assert vault.logins == 1
    clock[0] = 1_000.0  # well past the 60s lease
    assert resolver.resolve("vault://secret/a#k") == "v"
    assert vault.logins == 2


def test_a_revoked_token_is_retried_once_with_a_fresh_login():
    """Revocation is the rotation case: the cached token stops working
    mid-life and the next resolution has to recover by itself."""
    resolver, vault = make_vault({"secret/a": {"k": "v"}})
    assert resolver.resolve("vault://secret/a#k") == "v"
    vault.revoke_all()
    assert resolver.resolve("vault://secret/a#k") == "v"
    assert vault.logins == 2


def test_a_rotated_value_is_picked_up_on_the_next_resolution():
    """A-4's gate in miniature: the new value is written to vault ONLY,
    nothing is restarted, and the next resolution sees it. This is also
    why the reference shape carries no version pin."""
    resolver, vault = make_vault({"secret/a": {"k": "old"}})
    assert resolver.resolve("vault://secret/a#k") == "old"
    vault.put("secret/a", {"k": "new"})
    assert resolver.resolve("vault://secret/a#k") == "new"


def test_missing_secret_is_a_vault_stage_auth_error():
    resolver, _ = make_vault()
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("vault://secret/nope#dsn")
    assert excinfo.value.code == "auth_error"
    assert excinfo.value.retryable is False
    assert excinfo.value.detail == {"stage": "vault"}
    assert "secret/nope" in str(excinfo.value)


def test_missing_field_names_the_field_and_not_the_other_keys():
    """Listing the keys that *are* there would be a useful hint and a
    schema leak. The caller already knows what they asked for."""
    resolver, _ = make_vault({"secret/a": {"dsn": "v", "password": "hunter2"}})
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("vault://secret/a#token")
    message = str(excinfo.value)
    assert "'token'" in message
    assert "password" not in message
    assert "hunter2" not in message


def test_a_refused_runner_identity_says_so_without_echoing_it():
    vault = FakeVault()
    vault.put("secret/a", {"k": "v"})
    resolver = VaultResolver(
        "https://vault.invalid",
        VaultAuth(role_id="wrong-role", secret_id="wrong-secret-id"),
        session=vault,
    )
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("vault://secret/a#k")
    message = str(excinfo.value)
    assert "login refused" in message
    # The runner's own credential must not ride along in the message —
    # a failed login body can echo what was sent (JC-8).
    assert "wrong-secret-id" not in message


def test_an_unreachable_vault_names_the_address_and_the_error_type():
    import requests

    class Dead:
        def post(self, *args, **kwargs):
            raise requests.ConnectionError("connection refused to 10.0.0.1:8200")

        def get(self, *args, **kwargs):
            raise requests.ConnectionError("connection refused")

    resolver = VaultResolver(
        "https://vault.invalid", VaultAuth(role_id="r", secret_id="s"), session=Dead()
    )
    with pytest.raises(VaultResolutionError) as excinfo:
        resolver.resolve("vault://secret/a#k")
    assert "unreachable" in str(excinfo.value)


def test_no_vault_identity_configured_is_refused_at_construction():
    with pytest.raises(VaultResolutionError):
        VaultAuth.from_env({})
    with pytest.raises(VaultResolutionError):
        VaultResolver.from_env({"VAULT_ROLE_ID": "r", "VAULT_SECRET_ID": "s"})  # no addr


def test_a_dev_server_token_works_without_approle():
    """`VAULT_TOKEN` is the dev-mode path only — supported so the pilot
    can stand vault up in one command, never as a production posture."""
    vault = FakeVault()
    vault.put("secret/a", {"k": "v"})
    vault.issued.append("dev-root-token")
    resolver = VaultResolver(
        "https://vault.invalid", VaultAuth(token="dev-root-token"), session=vault
    )
    assert resolver.resolve("vault://secret/a#k") == "v"
    assert vault.logins == 0


# --- the seam: both schemes at once, during and after the migration ---------


def test_the_router_resolves_both_schemes_during_the_migration():
    """A-4 flips references one connection at a time, so a runner mid-flip
    holds a registry with both kinds and must serve either."""
    vault_resolver, _ = make_vault({"secret/a": {"k": "from-vault"}})
    router = SchemeRouter({
        VAULT_SCHEME: vault_resolver,
        ENV_SCHEME: EnvResolver({"LEGACY": "from-env"}),
    })
    assert router.resolve("vault://secret/a#k") == "from-vault"
    assert router.resolve("env://LEGACY") == "from-env"


def test_a_surviving_plaintext_reference_announces_itself(caplog):
    """The migration's own progress bar: every remaining `env://` says so
    in the runner log, by reference and never by value."""
    router = SchemeRouter({ENV_SCHEME: EnvResolver({"LEGACY": "still-plaintext"})})
    with caplog.at_level(logging.WARNING, logger="connectors.sdk.vault"):
        assert router.resolve("env://LEGACY") == "still-plaintext"
    assert "PILOT-ONLY" in caplog.text
    assert "env://LEGACY" in caplog.text
    assert "still-plaintext" not in caplog.text


def test_env_references_are_unresolvable_once_the_env_leg_is_dropped():
    """`resolver.allow_env: false` is how "the estate is migrated" stops
    being a claim and becomes a mechanism."""
    vault_resolver, _ = make_vault({"secret/a": {"k": "v"}})
    router = SchemeRouter({VAULT_SCHEME: vault_resolver})
    assert router.resolve("vault://secret/a#k") == "v"
    with pytest.raises(VaultResolutionError) as excinfo:
        router.resolve("env://LEGACY")
    assert excinfo.value.code == "auth_error"
    assert "no resolver for its scheme" in str(excinfo.value)


def test_the_router_refuses_a_scheme_nobody_owns():
    router = SchemeRouter({VAULT_SCHEME: make_vault()[0]})
    with pytest.raises(VaultResolutionError):
        router.resolve("awssm://some/secret")
