# A-5 — the knowledge floor: built, staged, and honestly not closed

Checkpoint A-5 under **D-119**. Three of the four gate clauses now have
their machinery and a prepared act; **none is closed**, because each ends
in a merge or a certification that belongs to the operator. What follows is
what landed, what it found, and what is still owed — in that order.

## 1. The golden suite goes home (D-119.2a)

`benchmark-seed-v0.yaml` was not merely in the wrong repository. It was
**package data in the validation wheel**, so every customer's KB CI
installed the pilot's ten requests, the pilot's verified SQL, and a frozen
copy of the pilot's snapshots. Its normative home is now
`.contextlayer/benchmark/suite.yaml` (KB spec **§3.1**), and wheel **0.7.0**
carries the checker instead of the customer.

The stale copy was already wrong, which is the argument in one line: the
snapshots travelling beside the suite had drifted from the KB's accepted
`supabase.json`. Goldens now resolve against **the KB's own snapshots**, so
a dropped column fails at the commit that drops it.

**KB-9 as shipped** (KB spec **§10.1**): schema + resolution, base-relation
column existence, contaminated-context as a **flag** — zero model calls, no
network, accuracy runs still manual. A KB with no suite prints that it
found none and passes; "nothing was checked" must not read like "everything
checked out" (D-116.4, one layer down), and that has its own test.

**Proved both ways** (KB PR #46; #47 opened against it, recorded, closed,
branch deleted):

| | result |
|---|---|
| the real suite | **pass** — 10 cases, 3 snapshots, 0 errors, 13 contamination flags |
| a golden referencing a dropped column | **fail** — `RB-01 golden-column: supabase.public.users.signed_up_at referenced but not in snapshot` |

**Removed, not merely superseded** (D-113.2): the platform keeps a frozen
copy under `fixtures/benchmark/`, labelled as a test input for the
checker's own tests and deliberately not the live suite. Every manual-kit
command that read a packaged default now takes `--suite`/`--snapshot`.

*Near-miss worth reading:* the workflow parses `runtime_deps` with an awk
that stops at the first non-list line, so the comment explaining the new
`sqlglot` pin — written inside the list — silently truncated it. Caught by
rehearsing the workflow's own commands locally before pushing.

## 2. Contamination triage becomes a mode (D-119.2b)

**S1c** (skill spec §6): the KB's own contamination state delivers the
batch. `worklist.py` ships in the skill bundle — stdlib-only, zero model
calls — joining each marker to the contaminating object's facts *now*
(including the `stats.checks` constraints SS-5 captures), dependency
resolution, prior certification, report-path membership, and which changed
columns the doc actually speaks about.

**It classifies nothing.** Judging whether a constraint confirms a
paragraph or contradicts it is reading; the tool assembles, the session
judges, the human certifies.

- **`confirms-prose` → a front-matter-only diff.** A *checkable* property,
  and the only reason thirty repairs are reviewable as thirty stamps.
- **`needs-re-grounding`** → rewrite from the snapshot, cite the constraint
  at DDL grade, name the disagreement.
- **`depends-on-missing-object`** → left contaminated. Deleting a
  dependency to turn a doc green removes the tripwire; it does not repair
  the room.
- **CP-E6** — a repair re-grounds, it does not re-certify. Docs land
  `draft`; the PR body hands the `verified` + `last_verified` act back by
  name, which under solo-operator mode is what the merge already is.

**Conformance, D-78-layered:** 18 validator tests over staged diffs, plus
**AS-19 behavioural PASS 5/5** (`results/phase2/a5/as19/`) on a batch staged
so each class is decidable from the evidence alone — with a falsifiability
script that mutates the real artifacts four ways and catches each.

## 3. The triage plan — and the three docs that are actually wrong

`results/phase2/a5/TRIAGE-PLAN.md`: **33 docs, four batches, paste prompts
per batch.** Every marker is one event — sync #34, the first run after
`CHECK` capture — so the expected shape is not thirty broken documents but
thirty nobody has re-read since the facts got sharper.

**30 `confirms-prose` · 3 `needs-re-grounding` · 0 `depends-on-missing-object`.**
The three, none visible from a marker:

- `ai_runs.md` and `ai_prompt_configs.md` — `flow_type` documented as an
  **11-value set**; the constraint admits **13** (`skills_pool`,
  `professional_summary` missing from both). They cross-reference each
  other, so they are wrong together and batched together.
- `v_jobs_by_status.md` — warns that `public.jobs.status` has **no** CHECK.
  It has one. That warning is the opposite of the truth and a report author
  would act on it.

**Two premises of D-119 corrected:** the set is **33**, not 34; and
`public.subscriptions` was **already repaired** during the B-1 closure run
(KB PRs #44/#45, plus the operator's own certification commit). No batch
carries it and none waits on the Stripe verdict — that question
(`4c4ecb3d`, plus the still-`batched` second filing `3f04d202`) is now an
ordinary enrichment PR against a `draft` doc.

## 4. The metrics catalogue (D-119.2c)

Ten drafts — KB PR #48 — from the ten goldens, the reporting views' own
definitions and the entity docs. **Implementations verbatim**, window
parameterised, nothing else touched; both routes where both exist, since
the `reporting.v_*` view is the only path returning rows under RLS; and the
doc says where two grains do not mix.

All `status: draft`, `owner: alper (operator) — pending`. Until they are
certified, a citing report says *draft* in its trust notes — correct
behaviour, and the reason drafting and certifying are separate acts.

Three seed cases produced **no** metric on purpose (RB-04 is a lens, RB-05
a composition, RB-03 a slice). Gaps live in the docs: `subscriptions.status`
has no DB CHECK and the table held 0 rows; `conversions` is where GA4 and
Supabase are *expected* to disagree; `activation-rate`'s steps are not
strictly nested. One caveat the estate has **closed**: RB-09's ungrounded
`'failed'` value is now DB-enforced.

**Named, not smuggled:** the `metric` front-matter class is still
unregistered in the validation library, so KB CI link-checks these docs and
does not schema-check them. Its own PR, with a wheel carry.

## 5. What did not run, and the defect behind it

**A5-F1 — the pilot deployment is unreachable.** `CORE_PUBLIC_URL` and
`CORE_OIDC_ISSUER` are pinned to `192.168.1.104`; the machine is now
`192.168.1.102`. The MCP endpoint's `www-authenticate` points at an OAuth
document on the dead host and `/v1/auth/login` redirects there too, so
**no session and no browser can sign in — localhost included.** A-2 closed
bundle staleness for *profile* changes; nothing watches the deployment's
own address, and every bundle compiled before the move is stale in a way
the existing mechanism cannot see.

The session did not restart the stack: trading a wrong address with a known
one-command fix for a possibly-dead stack with nobody present is not an
improvement. It is first on the STOP list.

**The floor check (task 3) is therefore NOT RUN**, and would still have
been the operator's: MCP is a browser sign-in under the reporter's own
identity (PA-1), and the gate's text needs a *certified* metric, which is
STOP-2. `results/phase2/a5/FLOOR-CHECK.md` records the attempt, the static
state of RB-01's path (one of three legs — the verified view — already
there), and the prepared re-run prompt.

## 6. Gate verdict — A-5 is NOT CLOSED

`results/phase2/a5/GATE-CHECK.md` grades playbook §9 items 3/4/6. All three
are open, each behind an operator act: the four triage batches (STOP-1),
the metrics merge and certification (STOP-2), and the KB-9 merge. Item 6's
baseline half additionally awaits BASELINE-1's own trigger, as §2.2 of the
phase-2 plan requires.

**Contamination at end state: 33 — unchanged.** The Python contamination
test is **still red**, correctly: it asserts the pilot KB has no
contaminated doc, and it has 33. Nothing was relaxed to make a suite look
better than the estate.

Suites: python **827 passed / 14 skipped / 1 failed** (that test). Core's
sources are untouched; the two suites that read the skill bundle —
`compile.test.ts` (13) and `conformance.test.ts` (24) — re-run green with
`worklist.py` shipping inside it.

**Fence:** exactly the two authorized amendments (KB §3.1 + §10.1; skill §6
S1c + AS-19). No B-3/B-4 surface, no BASELINE-1 run, no new MCP tool, no KB
content outside the skill-PR flows, nothing merged by the session.
