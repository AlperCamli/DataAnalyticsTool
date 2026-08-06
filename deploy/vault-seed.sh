#!/bin/sh
# Seed the dev Vault: enable KV v2, create the platform policies, and mint
# the AppRole identities the core and the runner authenticate as (A-4).
#
# Runs against the **dev-mode** Vault the compose stack starts — in-memory,
# auto-unsealed, root token known. That is a development posture and this
# script says so rather than pretending otherwise: a real deployment runs
# a sealed, persistent Vault and an operator does this once, by hand, with
# unseal keys they hold. What carries over unchanged is the shape — two
# AppRoles, two policies, least privilege between them.
#
#   docker compose exec vault sh /vault/seed.sh
#
# Idempotent: safe to re-run. Writes no secret VALUE — the pilot's own
# values are seeded by the migration runbook, from the operator's hands,
# and never from a file in git (JC-8).
set -eu

export VAULT_ADDR="${VAULT_ADDR:-http://127.0.0.1:8200}"
export VAULT_TOKEN="${VAULT_TOKEN:-dev-root-token}"

echo "vault: $VAULT_ADDR"

# Preflight: refuse to start against a sealed or uninitialised vault.
#
# Without this the first command (`secrets enable`, whose `|| true`
# swallows every error including this one) appears to succeed and the run
# dies three lines later on `Error uploading policy: ... Vault is sealed`
# — which reads as a policy problem and is not one. `operator init`
# re-seals the vault when it finishes, so arriving here sealed is the
# normal path, not an exotic one: it is what happens to everybody who
# runs init and then runs this.
status=$(vault status -format=json 2>/dev/null || true)
case "$status" in
  *'"sealed": true'*|*'"sealed":true'*)
    echo "refusing to seed: vault is SEALED." >&2
    echo "  Unseal it first, with the key from \`vault operator init\`:" >&2
    echo "    docker compose exec -T vault vault operator unseal \"\$VK\"" >&2
    echo "  Then check: \`vault status\` says Sealed false, Unseal Progress 0/1 clears." >&2
    exit 1 ;;
  "")
    echo "refusing to seed: cannot read vault status at $VAULT_ADDR." >&2
    echo "  Is the container up, and is VAULT_ADDR right?" >&2
    exit 1 ;;
esac
case "$status" in
  *'"initialized": false'*|*'"initialized":false'*)
    echo "refusing to seed: vault is NOT INITIALISED." >&2
    echo "    docker compose exec vault vault operator init -key-shares=1 -key-threshold=1" >&2
    exit 1 ;;
esac

# KV v2 at `secret/` — dev mode mounts this already; a fresh server may not.
vault secrets enable -version=2 -path=secret kv 2>/dev/null || true

# --- policies -----------------------------------------------------------
# Least privilege between the two identities, because they are not the
# same trust: the runner reads customer credentials and never core
# secrets; the core reads its own config and never a customer credential.
# A single "platform" policy would have been one line shorter and would
# have made the runner able to read the git token.
#
# BOTH the exact path and the subtree are granted, deliberately. Vault's
# `path "x/*"` does NOT match `x` — so a policy with only the glob denies
# a read of the secret sitting at the prefix itself, with a bare
# "permission denied" and nothing to say the rule never applied. Found by
# testing this script against a real Vault rather than by reading it.

vault policy write cl-core - <<'POLICY'
path "secret/data/contextlayer/core" {
  capabilities = ["read"]
}
path "secret/data/contextlayer/core/*" {
  capabilities = ["read"]
}
POLICY

vault policy write cl-runner - <<'POLICY'
path "secret/data/contextlayer/connections" {
  capabilities = ["read"]
}
path "secret/data/contextlayer/connections/*" {
  capabilities = ["read"]
}
POLICY

# --- AppRole identities -------------------------------------------------
vault auth enable approle 2>/dev/null || true

# secret_id_ttl=0: the pilot's runner is long-lived and nobody is on hand
# to re-issue at 03:00. token_ttl is short by contrast — that is the
# credential that actually moves, and the resolver re-logs in by itself.
vault write auth/approle/role/cl-core \
  token_policies=cl-core token_ttl=1h token_max_ttl=4h secret_id_ttl=0 >/dev/null
vault write auth/approle/role/cl-runner \
  token_policies=cl-runner token_ttl=1h token_max_ttl=4h secret_id_ttl=0 >/dev/null

echo
echo "AppRole identities (put these in the stack's env files):"
for role in cl-core cl-runner; do
  role_id=$(vault read -field=role_id "auth/approle/role/$role/role-id")
  secret_id=$(vault write -f -field=secret_id "auth/approle/role/$role/secret-id")
  echo "  $role"
  echo "    VAULT_ROLE_ID=$role_id"
  echo "    VAULT_SECRET_ID=$secret_id"
done

cat <<'NOTE'

These lines ARE the bootstrap remainder — the irreducible credential A-4
cannot put in vault, because they are what opens vault. In the dev stack
the equivalent is deploy/vault-dev.env (committed, dev-only, a toy). On
the pilot they go in .secrets/vault-core.env and .secrets/vault-runner.env
— two files, not one, because these are two identities under two policies
and a shared file quietly hands the runner the core's read of the git
token. Those two files are what remains of .secrets/ after the migration.
Stated in the playbook rather than hidden; a system that claims zero
bootstrap credentials is lying about where it kept one.
NOTE
