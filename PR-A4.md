# A-4 — Secrets have a supported home

Checkpoint A-4 (Track A), plus D-110.2's authorized compose fix and
D-110.3's filings, which rode task 0.

**What ends here.** Since CP-3a the runner has resolved credentials from
`env://NAME` — the runner's process environment or `.secrets/runner.env`,
which means a plaintext credential on the host. The seam was always
written for a real vault to land behind it ("Production vault schemes
land behind the same `resolve(ref) -> str` seam later; nothing above this
module changes when they do"). This is that landing. The core, which
never had a seam at all, gets one.

**What does NOT end here.** The gate's live half — the pilot migration
and the rotation proof — moves real credentials and deletes the last
plaintext copy of them. No session can run it. STOP-1.

---

## 1. Task 0 — the ruling, the compose fix, the filings

**The ruling is recorded as D-110, not D-109.** It arrived numbered
D-109; that number was already taken by the A-3/B-2 *build* session
(`ec1987b`), which the Phase-2 plan cites as "DECISIONS D-109". Two
D-109s with different clause contents would make every future citation
ambiguous. Clause mapping is one-for-one — the compose fix is D-110.2,
the capability-spec section D-110.3c. This session's own decisions are
D-111. **Affirmed by D-112.1.**

### 1.1 D-110.2 — compose-env precedence (third occurrence)

The rule now has a statable form: *a value a **deployment supplies**
lives in an env file; only a value **this compose file computes** lives
in `environment:`.*

Every feature toggle left `environment:` for `deploy/core.defaults.env`
(all off). Overlays win by plain list order:

```
docker-compose.yml            deploy/core.defaults.env, deploy/vault-dev.env
deploy/compose.mcp.yml     →  deploy/core.live.env
deploy/compose.live.yml    →  deploy/core.live.env, .secrets/vault-*.env, .secrets/sync.env
deploy/compose.baseline.yml → deploy/baseline/<condition>.env
```

`make stack-live` no longer sources anything into the shell.
`make stack-mcp` became an overlay rather than a shell assignment.
Verified by `docker compose config`: the live overlay resolves
`CORE_MCP_ENABLED=1` and `SYNC_ENABLED=1` **with an empty shell**, and
the baseline overlay still inverts sync to `0` on top of it — now by list
order rather than as a side effect of `environment:` ranking.

**The half the ruling's text did not anticipate.** The obvious escape
hatch — a bare pass-through entry, `environment: [- CORE_MCP_ENABLED]`,
which reads as "shell wins if set, env file otherwise" — **is the same
defect wearing a different hat.** Compose resolves the unset case to null
and the container ends up with the variable *unset*, wiping the env-file
value rather than deferring to it. Verified at runtime, not assumed, and
kept as `test_a_bare_passthrough_entry_is_not_an_escape_hatch`.

Consequence: there is no shell override for a toggle any more, which
would have quietly broken `CORE_MCP_ENABLED=1 make stack-live` — three
checkpoints of muscle memory. So the habit was made loud instead of
silent: `deploy/check-toggle-env.sh` runs ahead of every `make stack-*`
and refuses to start, naming the toggle and where to set it. Without that
guard this ruling would have traded one quiet failure for another.

**Effective flags.** `/healthz` reports the *whole* toggle set from
`FEATURE_TOGGLES` in `config.ts`, not three hand-picked fields — so a
toggle added without a line in the health packet is a failing test.
`migrate_on_start` joined as the first beneficiary. The set is a
three-way contract (config.ts reports it, `core.defaults.env` supplies
its off-state, `check-toggle-env.sh` refuses a shell export of it) and
`tests/test_compose_env_passthrough.py` asserts the three agree.

### 1.2 D-110.3 — filings

- **(a)** Governance writes leave no audit row — filed at dashboard spec
  **§5.1**, pointer on register row **U-12**. `audit_records` is one row
  per *MCP call* and is faithfully that, so connection CRUD lands
  nowhere; the durable trace today is the job's `triggers` array, which
  exists only where a job exists. Not fixed here: widening the contract
  is a ruling, not a patch. **Normative trigger: MUST close before B-4's
  audit view ships.**
- **(b)** D-107.3 (verdict history) and D-107.4 (jobs retention) filed as
  recorded at **§5.2**.
- **(c)** Capability-spec **§3.1** — the `test_connection` probe's three
  preflight surfaces, result shape, failure mapping, and the `unprobed`
  contract as **normative** (`unprobed` is not a pass; no consumer may
  render it as one). Placed under §3 rather than given its own section
  because §11/§12 are cited by number and renumbering would strand those
  citations. Conformance **CC-14/15/16** added for coverage that already
  existed undocumented; the three probe tests are tagged to them. **No
  behaviour changed.**

## 2. A-4 — the vault resolver

One reference syntax across the platform, identical in Python and
TypeScript:

```
vault://<mount>/<path>#<field>
```

KV v2's `/data/` segment is inserted by the resolver, not written into
the reference — so a KV version change rewrites one line, not every
registry row.

| Gate clause | How |
|---|---|
| One vault resolver behind the existing `resolver:` seam | `VaultResolver` + `SchemeRouter` in `connectors/sdk/vault.py`; `resolver.kind: vault` in the runner config. Nothing above the module changed |
| JC-8 canary green **through** it | `test_credential_injection_and_cleanup` **re-pointed, not duplicated** |
| `.secrets/` marked pilot-only in the playbook | §4.1, in those words |
| Playbook §4 matches reality | Rewritten to the shipped shape; the operator's run is what makes it *true* |
| Rotation verified live | **STOP-1 / task 4** |

**No version pin, deliberately** (D-111.1). `?version=N` is one
parameter and it is what the API offers — and it would have made this
checkpoint's own gate unprovable. A pinned reference is a rotation that
silently does not take: write the new value, watch nothing change, go
looking in the wrong place. That is D-84.2's family, which this
checkpoint exists partly to stop paying into. Always-latest is the
contract, and `test_a_rotated_value_is_picked_up_on_the_next_resolution`
asserts it.

**Two identities, two policies** (D-111.2). `cl-core` reads
`secret/contextlayer/core*`; `cl-runner` reads
`secret/contextlayer/connections/*`; neither reads the other's. A single
platform role would have been four lines shorter and would have given the
process that executes customer SQL a read of the KB git token — push
access to the customer's knowledge base. Verified refusing in **both**
directions against a real Vault.

**`env://` retained, marked PILOT-ONLY, made visible** (D-111.3). The
seam routes by scheme because the migration flips one connection at a
time. Three things keep "retained" from decaying into "supported": the
module docstring and playbook §4.1 say pilot-only in those words; every
`env://` resolution logs a warning naming the reference (never the
value), so the remaining plaintext-backed credentials are a `grep`
rather than an assumption; and `resolver.allow_env: false` turns a
survivor into a hard error. That flag is what makes "the estate is
migrated" a mechanism instead of a claim.

## 3. The core's own secrets

The core never had a resolver seam. It now resolves any config value
that *is* a `vault://` reference, at boot, **all-or-nothing** — the first
failure names the variable and the reference and the process exits. A
core on half its secrets fails later, elsewhere, with a worse error;
this is S-6's reasoning applied to boot.

Generic by design (D-111.4): no hand-maintained list of "the secret
variables", because such a list goes stale the first time someone adds a
config value, and its failure mode is a secret that silently stays
plaintext because its name was not on it.

`/healthz` gains `instance.vault` — `configured`, `reachable`, `sealed`,
`initialized`. Reachability, never contents; no address, because
`/healthz` is unauthenticated and an internal URL buys the operator
nothing they did not already type. `sealed` earns its place because a
persistent vault seals on every restart and that is the commonest way
this breaks.

## 4. Dev stack

`vault` service (dev-mode: in-memory, auto-unsealed, toy root token),
`deploy/vault-seed.sh` (KV v2, both policies, both AppRoles), and
`deploy/vault-dev.env` wired under D-110.2's discipline. `core` and
`runner` both `depends_on: vault: service_healthy`, because the core
refuses to boot on an unresolvable reference.

## 5. Findings — filed, not absorbed

`results/phase2/a4/FINDINGS.md`.

- **A4-F1 — the Connections module cannot edit a connection.** B-2 ships
  Add, Test and Remove, and the card renders no `config`. Changing one
  reference through the UI means retyping a config JSON the screen will
  not show you — five chances to silently drop a config key on five
  connections. **A missing screen, not a broken API**: the `PUT` is a
  correct idempotent upsert and its read-back caught nothing because
  nothing went wrong. The migration uses `flip-references.sh` instead
  (same governed API, read-modify-write, dry-run by default, verifying
  A-3's read-back after each write). Assigned by D-112.4 to **B-1**.
  Until a connection can be *edited* and its config *seen*, A-3's "wired
  without a DBA shell" is true for creating a source and not for
  changing one.
- **A4-F2 — dev-mode Vault is in-memory.** Harmless where the secrets
  are toys; destructive at A-4's own final step, because reducing
  `.secrets/` to the bootstrap remainder deletes the only other copy. A
  reboot would have cost a re-provisioned Supabase role, Google
  service-account key and Power BI secret. `deploy/compose.vault-file.yml`
  ships file storage on a named volume, and **the runbook gates
  `rm .secrets/runner.env` on it being in use with the unseal key stored
  off this disk.** Cost stated rather than hidden: that vault seals on
  every restart and there is no auto-unseal without a cloud KMS.
- **A4-F3 — a Vault policy glob does not cover its own prefix.**
  `path "secret/data/contextlayer/core/*"` does not match
  `secret/data/contextlayer/core`; the first draft granted only the glob
  and `cl-core` was denied its own secret with a bare `permission
  denied`. Caught by running the seed script against a real Vault, not
  by reading it — and it would not have been caught by any unit test
  here, because `tests/fake_vault.py` does not implement policy and
  deliberately still does not.

## 6. The bootstrap remainder

Vault cannot hold the credential that opens vault. What remains is
`VAULT_ADDR` plus one AppRole pair per identity —
`.secrets/vault-core.env` and `.secrets/vault-runner.env`, two files
because they are two identities under two policies. Named in playbook
§4.1 rather than hidden: a platform claiming zero credential files is
lying about where it kept one.

## 7. STOP-1

`results/phase2/a4/VAULT-MIGRATION-RUNBOOK.md` — nine acts, opening with
a **decision** (dev-mode or persistent) rather than a command, and
gating the irreversible step on it. `flip-references.sh` beside it,
dry-run verified against the live pilot: 5 references across 4
connections, nothing written.

Task 4 is blocked behind that run: the rotation proof, the `.secrets/`
inventory with a reason per surviving line, the post-run playbook §4
check, the gate check, and closure.

## 8. Verification

**Against a real Vault container**, not only fakes: AppRole login, KV v2
read, token reuse and re-login on expiry and on revocation, a rotated
value picked up with no restart, the policy split refusing in both
directions, boot refusing to proceed half-resolved, and no secret in any
error message. What is **not** verified is any of that against the
pilot's own credentials — precisely what STOP-1 is for.

**Suites at this commit:** core **306 passed / 4 skipped / 28 files**
(+20 from `core/test/vault.test.ts`); python **777 passed / 14 skipped /
1 failed** — the contamination triage, **now 35 docs, not 34**, estate
state, untouched by this work.

**Live state:** the pilot stack was not restarted by this session. Files
changed; containers did not. `/healthz` still answers `ok` with the
dashboard on, five connections registered, `ga4` and `gsc` still red on
staleness (D-110.4c).
