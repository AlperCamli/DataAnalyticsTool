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

---

## A4-F4 — sourcing an env file in a shell is not what Compose does

**Found during the migration itself, 2026-08-06.** Act 4 loaded the
pilot's credentials with `set -a; . .secrets/runner.env; set +a` and
wrote them into vault. Four of the five moved correctly. The fifth —
`GOOGLE_SA_KEY_JSON`, the Google service-account key — arrived in vault
**44 characters shorter than the value the runner actually had**, and no
longer parsed as JSON.

| | length | parses as JSON |
|---|---|---|
| shell-sourced from `.secrets/runner.env` | 2332 | **no** |
| what Compose passed the runner | 2376 | yes |

Docker Compose's env-file parser and a POSIX shell disagree about quoting
and escaping, and a service-account key is the one pilot credential with
enough embedded `\n` and quote characters for the disagreement to show.
The other four are flat strings, so they were byte-identical and passed.

**Why the runbook's own check did not catch it.** Act 4 verified the
round-trip by comparing vault's stored value to the *shell-sourced*
variable — the same interpretation on both sides of the comparison, so it
could only ever agree with itself. It confirmed vault stored what it was
given; it could not confirm that what it was given was right.

**How it surfaced.** `ga4` and `gsc` probed `config_error` with
`service-account key ... could not be parsed (contents not echoed; check
the key)`. That message did its job — it named the failing surface, told
the operator where to look, and refused to echo the value while doing it.

**Fixed, and the fix is the general rule:** take the value from the
**running container's environment**, which is by definition the value
that works today, not from a re-interpretation of the file it came from.

```bash
SA=$(docker compose exec -T runner printenv GOOGLE_SA_KEY_JSON)
docker compose exec -T -e VAULT_TOKEN="$VT" vault \
  vault kv put secret/contextlayer/connections/google sa_key_json="$SA"
```

**And the verification rule that follows:** compare the stored value
against the container's env by hash, never against the source you just
read. Doing that for all five found exactly one mismatch and proved the
other four.

**Where it closes.** The runbook's act 4 is rewritten to the container-env
method. Worth generalising beyond A-4: any future migration that moves a
credential between two systems must verify against the *consumer's* copy,
not the producer's, because only the consumer's copy is evidence that
anything works.

---

## A4-F5 — browser sign-in fails on a same-machine stack, out of the box

**Found 2026-08-06, first time anyone opened the dashboard sign-in on the
host that runs the stack.** Clicking **Sign in** redirects to

```
http://host.docker.internal:8180/authorize?...
```

and the browser cannot resolve `host.docker.internal`. The site simply
cannot be reached; nothing in the product reports a fault, because
nothing in the product is at fault yet — the redirect is well-formed and
the IdP is healthy.

**Why the default is what it is.** `docker-compose.yml` sets
`CORE_OIDC_ISSUER` and `DEVIDP_HOST` from `${CL_HOST_ADDR:-host.docker.internal}`.
That default is correct for the *core*: Docker Desktop routes
`host.docker.internal` from a container to the host's loopback, so
discovery and token introspection work. It is wrong for the *browser*,
which has no such name — Docker Desktop does not add it to the host's
`/etc/hosts`.

**Why it survived A-2.** The second-human run put the colleague on a
different machine, so that runbook required the dev-IdP exposure step
(`CL_HOST_ADDR=<LAN IP>`, `CL_BIND=0.0.0.0`). Under those settings the
issuer resolves for browser and container alike. The same-machine
loopback path — the configuration a customer operator tries **first** —
was never exercised.

**Why no in-product workaround exists.** `core/src/devidp.ts` builds
every advertised endpoint from one string (`issuer = http://${DEVIDP_HOST}:${port}`),
and `core/src/oidc.ts` uses the single configured `oidcIssuer` for
discovery *and* introspection. So there is no way to advertise one host
to the browser and use another server-side; the name has to resolve
identically from both.

**Immediate unblock** (loopback only, no LAN exposure, no restart):

```bash
sudo sh -c 'echo "127.0.0.1 host.docker.internal" >> /etc/hosts'
```

**Where it closes, and what the real fix is.** Playbook §4's exit
condition is "dashboard reachable, **OIDC login works**" — which does not
hold as written for a single-machine install, so this is a playbook-grade
defect, not a local annoyance. Two candidate fixes, for the checkpoint
that owns the dashboard's install story:

1. **Split external from internal.** Add an internal-only URL (the
   compose service name, `http://devidp:8180`) used for discovery and
   introspection, while the advertised issuer stays browser-resolvable.
   Costs care around OIDC's issuer-match validation.
2. **Default to `127.0.0.1` and document the exception.** Make the
   same-machine case work with no setup, and require `CL_HOST_ADDR` only
   for the genuinely multi-machine case (which A-2 already documents).
   Cheaper, and matches which case is common.

Either way the playbook needs a line: an install where the browser and
the stack share a host is the normal case and must not need `/etc/hosts`
surgery.
