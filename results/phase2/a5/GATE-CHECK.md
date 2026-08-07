# A-5 gate check — playbook §9 items 3, 4, 6

Graded 2026-08-07 against KB `main` `6bea39d` and platform `main` after
this session. **Verdict: A-5 is NOT CLOSED.** All three items remain open,
each behind an act only the operator can perform. What the session built is
listed against each so the remaining distance is visible rather than
implied.

## Item 3 — "Hot objects documented; all L1-derived report-path docs human-verified"

**OPEN — and this is the item with the most distance left.**

| | |
|---|---|
| Verified docs in the KB today | **2** (`v_user_signups_by_day.md`, `entities/page.md`) |
| Contaminated | **33** |
| Draft | 11 |

**Built this session:** the mode that closes it — enrich S1c (skill spec §6,
`worklist.py`), conformance-tested and behaviourally proven (AS-19 PASS
5/5), plus the plan that applies it to this estate:
[`TRIAGE-PLAN.md`](TRIAGE-PLAN.md) — 33 docs, four batches, every doc
classified with its evidence, four paste-ready prompts.

**What remains, and whose it is:** the four batches are steward sessions in
`~/cl-steward` (STOP-1), and the certification of each repaired doc is the
operator's own commit before merge (D-116.3). The session cannot run them
and must not merge them.

**Three defects the plan already surfaces**, none visible from a
contamination marker: `ai_runs.md` and `ai_prompt_configs.md` both document
`flow_type` as an 11-value set where the constraint admits 13, and
`v_jobs_by_status.md` warns that `public.jobs.status` has no CHECK when it
has one. Those are wrong claims being served today.

## Item 4 — "Every seed request resolves to entities + certified metrics"

**OPEN — the catalogue exists as drafts; certification is STOP-2.**

**Built this session:** ten metric docs drafted from the estate's own
verified SQL — KB PR **#48** — with implementations verbatim, per-system
routes (base table and reporting view), owners set to the operator, and
gaps named in the docs. Three seed cases deliberately produced no metric,
with the reason recorded.

**What remains:**

1. the operator reviews and merges #48;
2. flips each accepted metric to `verified` + `last_verified` under their
   own name (the metric class's certification rule, KB §4.4);
3. the item's own check — "checked by running `search_context` per
   request" — needs the MCP surface, which is **down** (A5-F1 below).

**Named gap, not a blocker for this item but adjacent to it:** the `metric`
front-matter class is unregistered in the validation library, so KB CI does
not schema-check these docs. Recommended as its own PR with a wheel carry.

## Item 6 — "Benchmark baseline recorded and CI-wired"

**PARTIAL, and the split is by design.**

**CI-wired: DONE, and proven both ways** — KB PR **#46** carries the suite
to `.contextlayer/benchmark/suite.yaml` and the KB-9 step that checks it.

- real suite → [run 31214259952](https://github.com/AlperCamli/Sample-Knowladge-Base/actions/runs/31214259952) **pass** (10 cases, 3 snapshots, 0 errors, 13 flags)
- doctored golden → [run 31214288955](https://github.com/AlperCamli/Sample-Knowladge-Base/actions/runs/31214288955) **fail**, naming `supabase.public.users.signed_up_at`

*Live on merge* — the PR is the operator's to merge, so today the check is
armed and demonstrated, not yet enforcing.

**Baseline recorded: NOT DONE, deliberately.** The three-condition accuracy
baseline is **BASELINE-1**, trigger-gated by D-96.3 and §2.2 of the phase-2
plan (first customer conversation that quotes value; ≈8–13h of operator
attention, booked, never squeezed in). A-5's own scope says the deterministic
half only. This item cannot fully close until BASELINE-1 runs, and pretending
otherwise would be the exact softening the exit-criteria rule forbids.

## The blocker that outranks all three — A5-F1

**The pilot deployment is unreachable.** `CORE_PUBLIC_URL` and
`CORE_OIDC_ISSUER` are pinned to `192.168.1.104`; the machine is now on
`192.168.1.102`. The MCP `www-authenticate` and the dashboard's login
redirect both point at the dead address, so no session and no browser can
sign in — over localhost or otherwise. Full diagnosis and the one-command
fix: [`FLOOR-CHECK.md`](FLOOR-CHECK.md).

Everything on the STOP list below assumes this is fixed first.

## Contamination at end state

**33 docs — unchanged from the session's start.** The session built the
tooling, wrote the plan and left the estate alone, because every repair
lands as a PR somebody has to read and certify.

The Python contamination test (`test_no_contamination_in_current_kb`) is
**still red**, and correctly so: it asserts the pilot KB carries no
contaminated doc, and the pilot KB carries 33. It goes green when the
batches land — not before, and nothing was relaxed to make a suite look
better than the estate.

## The STOP list, in order

1. **Fix the address** (A5-F1): `CL_HOST_ADDR=$(ipconfig getifaddr en0) make stack-pilot`, then confirm `/healthz` reports it. Re-download or recompile any bundle.
2. **Merge KB PR #46** — arms KB-9 on every future PR.
3. **Run the four triage batches** (STOP-1, `TRIAGE-PLAN.md`), certifying each accepted doc under your own name before merge.
4. **Review and merge KB PR #48**, then flip the metrics you accept to `verified` (STOP-2).
5. **Re-run the floor check** (`FLOOR-CHECK.md` carries the prompt) and save its trust notes.
6. Re-grade this file. Items 3 and 4 close on 3–5; item 6 closes on 2, with the baseline half still awaiting BASELINE-1's trigger.

Still riding, unchanged from D-119.3: the Stripe verdict for ledger
`4c4ecb3d` (an ordinary enrichment PR now — `subscriptions.md` was repaired
during the B-1 run and is not in the triage backlog), and the out-of-band
pile — vault rekey, root-token revoke, four `SECRETS-INVENTORY.md` rows.
