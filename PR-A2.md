# A-2 — setup delivery is a product surface (build half)

Phase-2 checkpoint **A-2**, built to the point where what remains is the
operator's and the colleague's: the second-human run itself. Task 0
applies ruling **D-106**; tasks 1 and 2 close **PA-1** and **PA-2**'s
mechanisms; task 3 writes the two artifacts the run needs and stops.

Spec diffs lead, per the amendment fence. Exactly the amendments
D-106.2/.4/.5 name, nothing else.

## 1. Spec amendments (additive; diffs lead)

**`specs/job-protocol-spec.md`** (D-106.2)

- §4.3 — one line under the state diagram naming the additive terminal
  transition `leased/running ─ defer ─► coalesced`, taken only when a
  duplicate for the same `(system, type)` is already queued.
- §5 — the amendment paragraph: why it is a coalesce and not a
  dead-letter (J-5: nothing failed), what terminates, what survives, and
  the load-bearing half — **the survivor adopts the later `not_before`
  of the two**, because the deferral's `retry_after_s` is a statement
  about the source and a survivor released early walks back into the
  same wall. Also states what is unchanged: deferral accounting, the §5
  cap ordering, and that interactive jobs never coalesce.
- §10 — **JC-11**.

**`specs/fault-ledger-schema-spec.md`** (D-106.4, D-106.5)

- §4 — proposal bound decoupled from `description` at **2000**, with the
  ruling's rationale (the defense is the LED-R2 scrub, not brevity).
- §4 — recurrence after rejection reopens, symmetric with L-4: verdict
  preserved, counts cumulative, `reopen_count += 1`, re-rejection
  permitted. States the limitation honestly: the columns hold the
  latest verdict only.
- §11 — FL-10 extended to cover the rejected-request case.

## 2. Task 0 — D-106

| Change | File |
|---|---|
| `coalesced` terminal state | `core/migrations/0010_defer_coalesce.sql` |
| `coalesceIntoQueued` + `deferJob` outcome | `core/src/queue.ts` |
| JC-11 (3 tests) | `core/test/conformance.test.ts` |
| `PROPOSAL_MAX = 2000` | `core/src/ledger.ts` |
| `rejected` in the L-4 reopening set; verdict preserved | `core/src/ledger.ts` |
| `reopen_count` on the read shape | `core/src/ledger.ts`, `core/src/dashboard.ts` |
| proposal-bound + rejection-recurrence tests | `core/test/dashboard-ledger.test.ts` |

The collision PR-B0 reported is reproduced deterministically by JC-11 —
enqueue → claim → enqueue same key → defer — and
`property.test.ts > dedupe invariant` is green, which makes it the
regression witness rather than a quarantined flake (D-106.3).

## 3. Task 1 — the download (PA-1 closes, mechanism half)

`core/src/setup.ts`, mounted with the dashboard's session layer:

- `GET /v1/setup/bundle` — authenticated (session cookie **or** the
  caller's own bearer token, same verifier), CSRF-exempt GET, role-gated
  through the KB's `roles.yaml`. Returns a deterministic `tar.gz` of
  `.mcp.json`, `CLAUDE.md` and the skill tree.
- `GET /v1/setup/status` — the same binding, plus the staleness answer,
  for a runbook or a script.
- The profile is **never** addressable: `?profile=…` is a
  `400 profile_not_addressable`, so the §3 rule ("a URL never carries a
  profile name") is asserted rather than merely unimplemented.
- No binding → `403 no_profile_binding` naming what an operator must
  add. Two bindings → `409 ambiguous_binding` (D-107.3).
- A browser gets `302` into the login flow; a script keeps the `401`
  (D-107.4), so the address handed to a first user *is* the download.
- The compile happens on request — no cache, no invalidation rule
  (D-107.1).

**`core/Dockerfile` now ships `core/skills/`** (D-107.5). Without it the
first real download answers `503 setup_uncompilable`: every compile
until today ran from a host checkout where the directory sits beside
`dist/`. Verified inside the built image, not only in tests.

## 4. Task 2 — staleness (PA-2 closes, mechanism half)

- `compileProfile` digests the bundle's contract-bearing bytes — server
  URL, `CLAUDE.md`, every skill file — into a 16-hex `stamp`, and writes
  it into the compiled `.mcp.json` URL as `&setup=<stamp>`.
- The MCP handler recomputes the current stamp per (KB state × profile),
  compares, and returns the notice as the server's `instructions` in the
  `initialize` result. No tool result shape changed; no MCP-spec surface
  is touched.
- Absent stamp → `SETUP UNVERIFIABLE` rather than silence: every bundle
  compiled before today is in that class, including the July-29 one.
- The compiled `CLAUDE.md` gains a closing section stating the rule the
  July-29 session did not have: the tool list here is a snapshot, the
  server's list is authoritative and can only be wider, and here is the
  one-step refresh URL.

## 5. Tests

`core`: **267 passed / 24 files**, all green (B-0 landed at 250/23).

| Suite | Tests | What it holds |
|---|---|---|
| `setup-bundle.test.ts` (new) | 11 | PA-1: own binding from the identity, profile-not-addressable, 401/302, role gate, ambiguity refused, layout incl. skill tooling, byte-identical downloads, **no credential** (canaries in the compile's environment + every configured secret, searched in the archive's bytes and its unpacked text). PA-2: the 2026-07-29 shape repeated end to end |
| `conformance.test.ts` | +3 | JC-11 and its two neighbours |
| `dashboard-ledger.test.ts` | +2 | 2000-char bound with the scrub intact; rejected → refiled → reopened with the verdict legible |
| `compile.test.ts` | +1 | the stamp is stable per profile state and moves on a tool grant or a skill edit |

The PA-2 test is the one worth reading: compile → connect clean (no
notice) → grant the profile a new tool → **reconnect on the same stale
bundle and assert the notice fires** → download again → the new grant is
in the bundle and the notice is gone. That is the July-29 sequence with
the silence replaced.

`python`: **744 passed / 14 skipped / 1 failed** —
`test_no_contamination_in_current_kb`, which asserts the operator's live
KB clone carries no contaminated docs and currently finds 34. KB PR #34
is merged; the re-verification campaign it feeds is the operator item
D-106.6 names. Estate state, not code.

## 6. What this PR does not do

The A-2 gate's human half. `results/phase2/a2/` carries
`COLLEAGUE-BRIEFING.md` and `A2-RUNBOOK.md`; the run is the operator's
and the colleague's, per D-104. Evidence extraction, field notes and the
gate check follow the run.

## 7. Flagged, not acted on (fence held)

1. **Verdict history depth.** D-106.5's "prior verdict history
   preserved" is implemented as *the verdict survives the reopen*; the
   columns still hold one verdict, so a second rejection overwrites the
   first reason (`reopen_count` keeps the tally). A per-verdict log is
   new DDL and a new register item, not a patch.
2. **Coalesced jobs and retention.** `coalesced` rows are terminal and
   never swept; `jobs` has no retention rule at all today. Worth a
   ruling when the first customer's queue is a year old, not now.
