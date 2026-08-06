# A-4 — moving the pilot's secrets into vault (operator runbook)

One machine: this Mac, the live pilot stack. Roughly 45 minutes, most of
it waiting for containers.

Read the page once before starting. **Act 1 is a decision, not a
command** — make it before you touch anything.

At the end, `.secrets/` holds two files instead of eleven, and the two it
holds are the credential that opens vault. That remainder is the honest
answer, not a shortfall; it is written down in playbook §4.1 for the same
reason it is written down here.

---

## 0. What this run proves

| # | A-4 gate clause | How this run shows it |
|---|---|---|
| 1 | One vault resolver behind the existing `resolver:` seam, JC-8 canary green through it | Machine-checked before this page existed — see below |
| 2 | `.secrets/` path marked pilot-only in the playbook | Playbook §4.1, shipped |
| 3 | Playbook §4 matches reality | This run is §4.1 followed literally; act 8 is the check |
| 4 | Rotation of one credential through the vault path verified live | Act 7 — the exec-role password, written to vault only |

**Already machine-checked, before this page:** the JC-8 canary
(`tests/test_sdk_service.py::test_credential_injection_and_cleanup`) was
**re-pointed**, not duplicated — the same canary that has guarded
credential injection since CP-3a now stores its secret in vault, resolves
it through `VaultResolver` under an AppRole login, and still asserts the
value reaches no outgoing message. 28 resolver tests
(`tests/test_sdk_vault.py`), 20 core-side tests
(`core/test/vault.test.ts`), and a live check against a real Vault
container: AppRole login, KV v2 read, the policy split holding in both
directions, and boot refusing to proceed half-resolved.

**What no session could do, and this run does:** move the pilot's real
credentials, and prove a rotation lands without a file being edited
anywhere.

## 1. Words used below

- **Reference** — `vault://<mount>/<path>#<field>`. The product stores
  this string; the value lives in vault. `env://NAME` is the pilot-only
  predecessor: it means the value is in plaintext on this host.
- **Bootstrap remainder** — `VAULT_ADDR` plus one AppRole
  `role_id`/`secret_id` pair per identity. Vault cannot hold the
  credential that opens vault.
- **Sealed** — a persistent vault encrypts itself at rest and needs an
  unseal key after every restart. `/healthz` reports it.

---

## Act 1 — the decision: dev-mode or persistent

**Dev-mode** (`docker compose up` as it stands) is in-memory. Every
restart loses every secret.

**Persistent** (`deploy/compose.vault-file.yml`) survives restarts and
costs you an unseal step after each one.

> **If you intend to delete `.secrets/` at the end of this run — and act
> 8 does — you must choose persistent.** Otherwise the next reboot
> destroys the only copy of credentials that took an afternoon to
> provision, and there is no file left to restore them from. This is the
> one irreversible ordering on the page.

The rest of this runbook assumes **persistent**. If you would rather
rehearse on dev-mode first, do the whole page with the base stack and
keep `.secrets/` — then repeat it for real. That is a reasonable choice
and costs one extra pass.

## Act 2 — stand vault up

```bash
cd ~/Desktop/DataProject
docker compose -f docker-compose.yml \
               -f deploy/compose.vault-file.yml \
               -f deploy/compose.live.yml up -d vault

# Wait for the listener. `up -d` returns when the CONTAINER is started,
# which is a second or so before Vault is accepting connections — run
# `vault status` on the next line and you get `connection refused`, which
# looks like a failure and is a race.
until docker compose exec -T vault vault status >/dev/null 2>&1 \
   || docker compose exec -T vault vault status 2>&1 | grep -q Sealed; do
  sleep 1
done
docker compose exec vault vault status
```

Expect this, and read all three lines:

```
Initialized        false
Sealed             true
Storage Type       file
```

`Storage Type file` is the one to check — it is how you know you are on
the persistent overlay and not the base stack's in-memory dev vault.

**Two things that look wrong here and are not:**

- **`vault status` exits 2.** That is Vault's exit code for "sealed",
  not an error. `echo $?` after it will say 2 until act 2 is finished.
- **`docker ps` shows the container `(health: starting)`, then
  `(unhealthy)` after five minutes.** The healthcheck is `vault status`,
  so an uninitialized or sealed vault is deliberately *not* healthy — a
  vault that cannot serve secrets should not report ready, and `core` and
  `runner` depend on `service_healthy` precisely so they do not boot into
  a failure. It flips to `healthy` within seconds of the unseal below,
  and recovers on its own however long you take. Take the time to store
  the keys properly.

**Initialise it.** This prints an unseal key and a root token **once**.

```bash
docker compose exec vault vault operator init -key-shares=1 -key-threshold=1
```

> `1-of-1` is a single-operator pilot choice, and a real deployment
> splits the key across people. Put the unseal key and the root token in
> your password manager **now**, before the next command. They are not
> recoverable and they must not land in this repo — `.secrets/` is
> git-ignored, but it is on the disk this vault is meant to get secrets
> off.

```bash
docker compose exec vault vault operator unseal <unseal-key>
docker compose exec vault vault status          # Sealed false
```

## Act 3 — policies and identities

```bash
docker compose exec -e VAULT_TOKEN=<root-token> vault sh /vault/seed.sh
```

This enables KV v2, writes the `cl-core` and `cl-runner` policies, enables
AppRole, and prints one `VAULT_ROLE_ID` / `VAULT_SECRET_ID` pair per
identity. Put them in two files — **two, not one**: they are two
identities under two policies, and a shared file quietly hands the runner
the core's read of the git token.

```bash
cat > .secrets/vault-core.env <<'EOF'
VAULT_ROLE_ID=<cl-core role_id>
VAULT_SECRET_ID=<cl-core secret_id>
VAULT_TOKEN=
EOF

cat > .secrets/vault-runner.env <<'EOF'
VAULT_ROLE_ID=<cl-runner role_id>
VAULT_SECRET_ID=<cl-runner secret_id>
VAULT_TOKEN=
EOF
```

`VAULT_TOKEN=` blanks the dev stack's root token, which the base compose
sets. `VAULT_ADDR` needs no line — `deploy/vault-dev.env` already points
at the in-network `http://vault:8200`, which is correct here too.

## Act 4 — seed the pilot's secrets

Vault is empty. Put today's values in it — **the values, one time, by
hand.** Read each one out of the file it is in now; do not retype from
memory, and do not paste any of them into a terminal that logs history.

```bash
# turn off history for this shell, so the values do not land in ~/.zsh_history
set +o history
```

The pilot has five secrets across five connections plus one core secret.
Their current homes are `.secrets/runner.env` and `.secrets/sync.env`.

```bash
# customer connection credentials → the cl-runner policy's subtree
docker compose exec -e VAULT_TOKEN=<root-token> vault \
  vault kv put secret/contextlayer/connections/supabase \
    introspect_dsn='<CL_INTROSPECT_DSN from .secrets/runner.env>' \
    exec_dsn='<CL_EXEC_DSN from .secrets/runner.env>'

docker compose exec -e VAULT_TOKEN=<root-token> vault \
  vault kv put secret/contextlayer/connections/google \
    sa_key_json='<GOOGLE_SA_KEY_JSON from .secrets/runner.env>'

docker compose exec -e VAULT_TOKEN=<root-token> vault \
  vault kv put secret/contextlayer/connections/powerbi \
    client_secret='<POWERBI_CLIENT_SECRET from .secrets/runner.env>'

# the core's own secret → the cl-core policy's subtree
docker compose exec -e VAULT_TOKEN=<root-token> vault \
  vault kv put secret/contextlayer/core \
    git_token='<SYNC_GIT_TOKEN from .secrets/sync.env>'

set -o history
```

> `ga4` and `gsc` share one service-account key today, which is why it is
> one secret at `connections/google` referenced twice rather than two
> copies. Two references to one secret rotate together, which is what you
> want here — it is one credential in Google's eyes.

**Check the policy split before going further.** This is the one place a
mistake stays quiet:

```bash
# a cl-runner token must NOT be able to read the core's git token
docker compose exec vault sh -c '
  vault write -field=token auth/approle/login \
    role_id=<cl-runner role_id> secret_id=<cl-runner secret_id> > /tmp/t
  VAULT_TOKEN=$(cat /tmp/t) vault kv get secret/contextlayer/core; rm /tmp/t'
```

Expect `permission denied`. If it prints a token instead, stop and re-run
act 3 — a runner that can read the git token is not least privilege, it
is one process away from pushing to the KB as the platform.

## Act 5 — restart the stack on its vault identities

```bash
docker compose -f docker-compose.yml \
               -f deploy/compose.vault-file.yml \
               -f deploy/compose.live.yml up -d --build core runner
curl -sS http://127.0.0.1:8100/healthz | python3 -m json.tool
```

`instance.vault` must read `configured: true`, `reachable: true`,
`sealed: false`. `mcp_enabled`, `sync_enabled` and `dashboard_enabled`
must all still be `true` — and note what you did **not** have to do to
get them there: no `set -a`, no `export`. That is D-110.2; if any of them
is `false`, the fix is an env file, not a shell (`make stack-live`
refuses a shell toggle now and says where to put it).

Nothing has moved to vault yet — every connection is still on `env://`
and still works. That is the point of doing this in two halves.

## Act 6 — flip the references

**This act does not happen in the browser, and that is a finding, not a
shortcut.** The B-2 Connections module can add, test and remove a
connection; it has no *edit* affordance. Changing one reference through
the UI means re-submitting the add form with the entire config JSON
retyped — and the card does not display config either, so you would be
retyping it from memory. On five connections that is five chances to
silently drop a config key. The gap is written up in
[`FINDINGS.md`](FINDINGS.md) as **A4-F1** and belongs to B-1/B-2's
follow-up; do not paper over it here.

Instead, use the helper, which is a client of the same governed API the
module uses and does a read-modify-write so the *only* thing that changes
is the references:

```bash
export CORE_TOKEN=$(curl -sS -X POST "http://127.0.0.1:8180/token" \
  -d grant_type=password -d username=<your-ops-user> -d password=<pw> |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

# 1. Dry run — prints every move it would make, writes nothing.
CL_TOKEN=$CORE_TOKEN results/phase2/a4/flip-references.sh
```

Expect exactly this, on the pilot's five connections:

| Connection | Old reference | New reference |
|---|---|---|
| `supabase` | `env://CL_INTROSPECT_DSN` | `vault://secret/contextlayer/connections/supabase#introspect_dsn` |
| `supabase` | `env://CL_EXEC_DSN` | `vault://secret/contextlayer/connections/supabase#exec_dsn` |
| `ga4` | `env://GOOGLE_SA_KEY_JSON` | `vault://secret/contextlayer/connections/google#sa_key_json` |
| `gsc` | `env://GOOGLE_SA_KEY_JSON` | `vault://secret/contextlayer/connections/google#sa_key_json` |
| `powerbi` | `env://POWERBI_CLIENT_SECRET` | `vault://secret/contextlayer/connections/powerbi#client_secret` |
| `looker_studio` | — | — (template-link; holds no credential) |

**Go one connection at a time, testing between each.** A failure names
the reference and tells you which of two things is wrong: `denied by
vault policy` means act 3's policy, `no secret at …` or `has no field …`
means act 4's spelling. Both are five-second fixes when you know which
connection just changed, and an afternoon when five did.

```bash
CL_TOKEN=$CORE_TOKEN results/phase2/a4/flip-references.sh --apply supabase
```

Then press **Test** on `supabase` in the browser at
`http://127.0.0.1:8100/app/`. Green means the runner logged in to vault
as itself and read the value. Repeat for `ga4`, `gsc`, `powerbi`.

> 📸 **Screenshot 1** — a connection card showing `vault://…` references
> and a green health dot.

The script re-reads each row after writing it and refuses to continue if
the store disagrees — A-3's read-back (D-109.1) doing its job on a
migration it was not written for.

If a test fails, the old reference still works — re-run the script's
mapping in reverse, or re-add through the UI. Nothing here is one-way
until act 8.

Also move the core's git token, which is not a connection:

```bash
# in .secrets/sync.env, replace the SYNC_GIT_TOKEN line's value with:
SYNC_GIT_TOKEN=vault://secret/contextlayer/core#git_token
docker compose -f docker-compose.yml -f deploy/compose.vault-file.yml \
               -f deploy/compose.live.yml up -d core
```

The core resolves that at boot. If it is wrong, the core **does not
start** and says which variable failed — deliberately, because a core
running on half its secrets fails later and worse.

> 📸 **Screenshot 2** — `/healthz` with `vault.reachable: true`, and the
> five connections all green.

**Confirm nothing is still on plaintext:**

```bash
docker compose logs runner | grep "PILOT-ONLY" | tail -20
```

Every `env://` resolution logs one line naming the reference. After a
`test_connection` on all five, this should print nothing new. If it names
a reference, that one did not get flipped.

## Act 7 — the rotation proof (the gate's fourth clause)

Rotate **one real credential by writing the new value into vault only.**
No file is edited. Nothing is restarted.

The exec-role password is the right one: it already has a reset script,
and a governed execute is the thing that proves it end to end.

```bash
# 1. Rotate the password at the source, and capture the new DSN.
#    This script prints the new value; the history guard still applies.
set +o history
.secrets/reset-exec-password.sh

# 2. Write the new DSN into vault. ONLY here.
docker compose exec -e VAULT_TOKEN=<root-token> vault \
  vault kv patch secret/contextlayer/connections/supabase \
    exec_dsn='<the new DSN>'
set -o history
```

`kv patch` leaves `introspect_dsn` alone. Now, **without restarting
anything**, run a governed execute in the browser — ask a question
through the MCP path that reaches a real query, or press **Test** on
`supabase` in the Connections module.

> 📸 **Screenshot 3** — a successful governed execute, after the
> rotation, with no restart.

It works because the reference carries no version pin: the runner reads
the latest value on the next resolution. That absence is the feature.

**Capture the evidence:**

```bash
date -u +%Y-%m-%dT%H:%M:%SZ > results/phase2/a4/rotation-window.txt
CL_TOKEN=$CORE_TOKEN CL_OUT=results/phase2/a4 \
  results/phase2/a3-b2/extract-connections.sh "$(cat results/phase2/a4/rotation-window.txt)"
```

## Act 8 — reduce `.secrets/` to the remainder

Only once acts 6 and 7 are green.

> **From here on, `make stack-live` is the wrong command.** It starts the
> base stack's dev-mode vault — in-memory, therefore empty — and the core
> will refuse to boot, naming the first reference it cannot resolve. Use
> **`make stack-pilot`**, which layers the persistent vault. The failure
> is loud either way; this just spares you diagnosing it.

```bash
ls .secrets/
```

Delete what has moved into vault:

```bash
rm .secrets/runner.env          # every reference in it is now vault://
```

Then close the door behind it — set `resolver.allow_env: false` in
`deploy/runner-config.yaml` and restart the runner. A surviving plaintext
reference is now an error instead of a warning, which is what turns "we
migrated" from a claim into a mechanism.

```bash
make stack-pilot        # the three-overlay command, as one target
```

Press **Test** on all five connections once more. All five green with
`allow_env: false` is the proof.

**Inventory what remains, and why each line is irreducible.** Write it
into `results/phase2/a4/secrets-inventory.md` — the gate asks for the
reasoning, not just the listing:

| File | Why it cannot move into vault |
|---|---|
| `.secrets/vault-core.env` | the credential that opens vault, for the core |
| `.secrets/vault-runner.env` | the same, for the runner, under a different policy |
| `.secrets/sync.env` | **not a secret file any more** — the token is now a reference; what is left is config (`SYNC_ENABLED`, the KB remote, provider, branch). Keep or move into git as you prefer |
| `.secrets/idp-users.json` | real people's dev-IdP accounts. A customer deployment has no such file — this is the pilot's stand-in for a customer IdP |
| `.secrets/connections.md`, `*.json`, `wire-*.sh` | operator notes and provisioning helpers. Check each: any that still contain a live credential value should be emptied now that vault holds it |

Be honest in that last row. If a helper script still has a password in
it, the migration is not finished, and writing "done" is worse than
writing "three files still hold values, here they are."

## Act 9 — the gate check

Re-read the A-4 gate against what you just did:

- [ ] One vault resolver behind the existing `resolver:` seam — JC-8 canary green through it
- [ ] `.secrets/` marked pilot-only in the playbook (§4.1)
- [ ] Playbook §4 matches reality — you followed it; note anywhere it lied
- [ ] Rotation of one credential through the vault path verified live (act 7)

**Write down every place the product failed to explain itself.** That is
the same instruction A-2 and A-3 carried, and it is the half no session
can supply. If act 4's `kv put` syntax was fiddly, or the Connections
module made flipping a reference harder than it should be, that is
A-4's field note and it is worth more than a clean checklist.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `vault status` → `connection refused`, right after `up -d` | the listener is a second behind the container | wait and re-run; act 2's `until` loop does this for you |
| `vault status` exits 2 | Vault's exit code for "sealed" | not an error; expected until act 2's unseal |
| Vault container `(unhealthy)` before act 2 finishes | the healthcheck *is* `vault status` | expected — it flips to healthy seconds after the unseal, and `core`/`runner` wait for it on purpose |
| `docker compose up` hangs on `core`/`runner` | vault is sealed, so its dependency is unmet | unseal it; the wait is the gate working |
| Core will not start, names a variable | that variable's `vault://` reference does not resolve | check spelling of mount/path/field; `vault kv get` it as root |
| `/healthz` shows `vault.sealed: true` | the host or the container restarted | `docker compose exec vault vault operator unseal <key>` |
| `/healthz` shows `vault.reachable: false` | vault container down, or `VAULT_ADDR` wrong | `docker compose ps vault` |
| A connection test says `denied by vault policy` | the identity's policy does not cover that path | act 3; remember `path "x/*"` does not match `x` |
| A connection test says `has no field` | the field name in the reference ≠ the key in vault | `vault kv get secret/...` as root and compare |
| Everything fails after a reboot | vault is sealed | unseal, then check `/healthz` |

**Rolling back** is always available until act 8: put the `env://`
references back through the Connections module and the old values are
still in `.secrets/runner.env`. After act 8 that file is gone, and the
way back is act 4 in reverse.
