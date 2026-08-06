# Persistent Vault for the pilot (A-4). File storage on a named volume,
# initialised and unsealed by the operator.
#
# The dev-mode server the base stack runs is in-memory: every restart
# loses every secret. That is exactly right for `docker compose up` on a
# developer's machine, where the secrets are toys — and exactly wrong for
# the pilot the moment `.secrets/` is deleted, because then vault holds
# the ONLY copy of credentials that took an afternoon to provision.
#
# So: do not delete `.secrets/` until the pilot is running this file and
# its unseal key is stored somewhere that is not this repo and not this
# disk. That ordering is the difference between a migration and an
# outage, and it is stated in the migration runbook as a gate.
#
# The cost, honestly: a persistent Vault seals itself on every restart
# and an operator must unseal it before the stack works. There is no
# auto-unseal without a cloud KMS, and adding one is a decision for the
# first customer deployment, not for a laptop.

storage "file" {
  path = "/vault/file"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

# The container cannot lock memory without extra privileges; the tradeoff
# is that secrets may reach swap. Acceptable on a single-operator pilot
# machine with an encrypted disk, and named here rather than left silent.
disable_mlock = true

api_addr = "http://vault:8200"
ui       = false
