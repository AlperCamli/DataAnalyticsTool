# A-4 findings

Written during the build, before the operator's run. Each is a place the
product did not do what the checkpoint assumed it could — recorded here
rather than absorbed silently, so the migration runbook can route around
them honestly and the right checkpoint can close them.

---

## A4-F1 — the Connections module cannot edit a connection

**What.** `core/web/src/Connections.tsx` ships Add (a `PUT` form), Test
and Remove. There is no edit affordance on a connection card, and the
card does not render `config` either — only system, connector, health
and credential references.

**Why it bit here.** A-4's migration is, at bottom, an *edit*: change one
credential reference, leave everything else alone. Through the shipped UI
that means re-submitting the add form with the whole config JSON typed
from memory, because the screen that would show you the current config
does not show it. On the pilot's five connections that is five chances to
silently drop a config key — and a dropped key in a connector config is
exactly the class of thing that surfaces two days later as a failed
snapshot.

**What the runbook does instead.** `results/phase2/a4/flip-references.sh`
— a client of the same governed API, doing a read-modify-write so the
only difference on the wire is the references. It is not a workaround for
a broken API; the API is fine (`PUT` is a correct idempotent upsert and
its read-back caught nothing because nothing went wrong). It is a
workaround for a missing screen.

**Where it closes.** B-1/B-2 follow-up. Two things, and the second
matters more than the first: an **edit** action on the connection card
that pre-fills from the stored row, and **config rendered on the card**
so an operator can see what they are about to change. Until both exist,
"a source is wired without a DBA shell" (A-3's gate) is true for
*creating* a source and not for *changing* one.

**Not a regression.** A-3's gate never claimed edit; it claimed CRUD over
the governed API with server-side role checks, and the `PUT` satisfies
it. This is a UI inventory gap that A-4 was the first work to actually
need.

---

## A4-F2 — dev-mode vault would have destroyed the pilot's secrets

**What.** The obvious reading of "stand up vault (or dev-mode for the
pilot)" is: run the dev-mode container the base stack already defines.
Dev-mode Vault is **in-memory**. Every restart loses every secret.

**Why it matters more than it sounds.** On its own that is an
inconvenience — re-seed and carry on. Combined with A-4's own final step
it is data loss: the gate reduces `.secrets/` to the bootstrap remainder,
which means the plaintext copies are *deleted*. After that, vault holds
the only copy of every credential in the estate, and a laptop reboot
would have required re-provisioning a Supabase role, a Google service
account key and a Power BI client secret from scratch.

**What was built.** `deploy/compose.vault-file.yml` — file storage on a
named volume, `vault operator init`, and an unseal step after every
restart. The base stack keeps dev-mode, correctly: there the secrets are
toys and a stack that does not start on the first command is a stack
people work around.

**The cost, stated rather than hidden.** A persistent vault seals on
every restart and needs an unseal key by hand. There is no auto-unseal
without a cloud KMS, and that decision belongs to the first real customer
deployment, not to a pilot on one Mac. `/healthz` reports
`vault.sealed` so the morning after a reboot costs one `curl`.

**The ordering is a gate, not advice.** The runbook refuses to reach act
8 (`rm .secrets/runner.env`) unless the persistent overlay is in use and
the unseal key is stored off this disk.

---

## A4-F3 — a Vault policy glob does not cover its own prefix

**What.** `path "secret/data/contextlayer/core/*"` does **not** match
`secret/data/contextlayer/core`. The first draft of
`deploy/vault-seed.sh` granted only the glob, and `cl-core` was denied a
read of the secret sitting at the prefix — with a bare `permission
denied` and nothing to say the rule had never applied.

**How it was caught.** By running the seed script against a real Vault
container and trying the read, rather than by reading the script. It
would not have been caught by any unit test in this repo, because the
fake vault in `tests/fake_vault.py` does not implement policy — and
deliberately still does not: a fake that models Vault's policy engine
would be a second implementation to keep honest, and it would have agreed
with whatever the first one did.

**Fixed.** Both the exact path and the subtree are granted, in both
policies, with the reason written above them so the next edit does not
quietly drop one.

**Worth generalising.** Anything in this repo that authorises by path
prefix deserves the same live check. The seed script is now the only
place we write a Vault policy, which keeps the blast radius to one file.
