# Context Layer — Phase 2 Development Plan (v1)

Status: ratified — D-98 (owner ruling, 2026-08-04) authorizes A-1 per this plan's gate, which is the ratification act this line awaited. Authorized by D-96.6; built from the CP-8 go/no-go report (results/cp8/go-no-go-report.md), whose Part 4/5 inventories and Track A/B proposal are this plan's requirements. Phase 1's plan conventions carry over unchanged: checkpoints are demonstrable events with mechanically verifiable gates; sequence and dependency only, no dates (OB-4 discipline — whose instrumentation this phase finally builds); a checkpoint is not closed while its work is unmerged (D-74.2).

## §1 Purpose

Phase 1 proved the machine end to end (M1 governed access, M2 governed execution, M3 text-to-report). CP-8's verdict: the platform passes, the playbook does not — GO vendor-assisted, NO-GO unassisted. Phase 2 makes the product usable by someone who is not the vendor: Track A turns onboarding into a product (the playbook grades PASS or ASSISTED-with-written-knowledge everywhere), Track B gives the product its visible surfaces (a thin dashboard that is a client of the governed API, never a second enforcement point).

## §2 Governing assumptions (operator-overridable, adopted as defaults)

1. **Product-feel leads.** No second customer is scheduled; the operator's stated priority is that the flow "feels like a product." Visible surfaces (B-1/B-2) are pulled forward in the serial order; unassisted onboarding completes later in the phase. Overriding this reorders §4, nothing else.
2. **BASELINE-1 stays trigger-gated** (first customer conversation that quotes value), per D-96.3's ruling — with the CP-8 cost estimate (≈8–13 h operator attention) recorded so the trigger firing books a two-day block, never an emergency. MC-1 remains blocked behind it, correctly.
3. **Standing constraint, verbatim:** no quantitative KB-value claim in any customer or demo material until BASELINE-1 lands.
4. **A second human touches the system this phase.** The role model has only ever been exercised by one person wearing every hat; the first non-operator user is a gate condition (A-2), because they will find the class of problems no session can.
5. **The no-UI boundary is normative** (CP-8 Part 5): profile/role changes, enrichment certification, drift merge, DDL application, report authoring, and KB content stay git/PR/session-native. The dashboard routes to them and never replaces them.

## §3 Checkpoint map and serial order

Two tracks; Track B gates nothing in Track A. Recommended serial order for a single operator, interleaved where surfaces are shared:

**A-0 → A-1 → B-0 → A-2 → A-3+B-2 → A-4 → B-1 → A-5 → B-3 → A-6 → B-4**

Milestones: **M4** = Track A exit (the playbook milestone: onboardable). **M5** = Track B exit (the dashboard milestone: operable by roles). Phase 2 closes at CP-Ω: both milestones + the phase retrospective.

## §4 Checkpoints

### Track A — product-flow hardening

**A-0 — Close the Phase-1 tail (chores only, per D-98).** The Act 2 / Act 3b re-runs are WAIVED by explicit owner acceptance (D-98.1, same class as D-80.2/D-95): both remain permanently recorded as attested-not-evidenced; the first customer-facing cross-source report is the de facto evidence point. *Gate (chores):* PR #30-class mislabel fixed (changelog graph-only case, D-97.1); RA-F 80%-of-limit publisher telemetry warning landed (D-96.3e); D-96.3 register rows not yet applied are applied; D-98 recorded; all suites green. A-0 folds into the A-1 session as its task 0.

**A-1 — The steward loop is whole.** *Demo:* a staged breaking change on the pilot estate is reviewed with the product's own tool. *Gate:* review-sync shipped per skill spec §7 with AS-7 green; live drill: staged break → sync PR → steward runs review-sync → repair PR → doc re-verified (playbook gate item 7, human half, first-ever rehearsal, recorded); `compile steward` succeeds again (F-7 hardening satisfied honestly, not relaxed); R-8 profile-skill test green.

**A-2 — Setup delivery is a product surface.** *Demo:* **a second human**, on their own machine, downloads their bundle and completes a reporter journey with the operator hands-off. *Gate:* authenticated bundle download served by the core, authorized server-side against the requester's own profile binding; bundle carries no credential; staleness closed (PA-2): a profile change after compile is detectable by the session or triggers recompile — demonstrated by repeating the 2026-07-29 failure shape and watching it *not* fail; the second-human journey's audit rows show their own identity end to end.

**A-3 — Connections are operable.** *Demo:* a source is wired, tested, and health-checked without a DBA shell or direct-DB write. *Gate:* connection CRUD + test over the governed API with server-side role checks; per-source health; an auth_error surfaces a re-auth prompt; the admin CLI becomes a thin client of the same API (no direct-DB path remains); the D-84-class silent-failure shape (claimed-registered, actually-absent) is structurally impossible — registration returns what the store now holds.

**A-4 — Secrets have a supported home.** *Demo:* the stack runs with zero plaintext credential files. *Gate:* one vault resolver behind the existing `resolver:` seam (JC-8 canary green through it); `.secrets/` path marked pilot-only in the playbook; playbook §4 matches reality; rotation of one credential through the vault path verified live.

**A-5 — The knowledge floor the gate assumes.** *Demo:* the playbook's §9 items 3/4/6 pass on the pilot estate. *Gate:* `metrics/` catalog seeded from the customer's own SQL with owners and per-system implementations; every report-path L1 doc human-verified (the certification act at scale, not n=1); benchmark integrity suite wired into KB CI (KB-9's deterministic half — accuracy runs stay manual per R7); the gate report re-run shows trust notes citing verified docs and a certified metric.

**A-6 — Onboarding measures itself.** *Demo:* a timed dry-run onboarding step records itself. *Gate:* OB-4 per-step timers implemented and armed; a rehearsal of playbook steps 2–4 on a scratch estate produces duration records; OB-4's row updated from "unstartable" to "armed, awaiting onboarding #2."

**M4 gate:** the playbook walk-through re-graded — every step PASS or ASSISTED-with-the-knowledge-now-written-down; §9 gate passes on the pilot estate; U-1..U-5 conditions closed or explicitly re-ruled.

### Track B — dashboard (gates nothing in Track A)

**Entry condition (spec-first, the JP-4/sync/authoring pattern):** the dashboard/UI spec is authored and merged before B-0 builds. Its requirements inventory is CP-8 Part 5 verbatim; its first ruling is the API-client rule; its §2 is the role→view matrix; the no-UI boundary list is a normative section; the auditor role is added to the server model before any auditor view exists.

**B-0 — Read APIs before pixels.** *Gate:* governed read endpoints for audit (U-12), publish deliveries (U-9), and ledger triage (U-5), each subject/role-filtered server-side, each with a conformance test proving a reporter cannot read another subject's rows; extract-audit.sh becomes a client of the audit API.

**B-1 — KB Health + ledger triage.** *Gate:* freshness map (consuming SO-F's sync_enabled at last — the two-silent-days failure shape now visible), doc-status counts, drift-PR queue routing to the git provider (no merge button — asserted), triage queue ordered by occurrences/distinct_subjects, LED-R5 neutralization asserted by test on the render path; gap resolution surfaces to the filer (F-10).

**B-2 — Connections module.** *Gate:* A-3's API gets its face; playbook step-3's exit ("dashboard reachable… health green") satisfiable as written by a customer operator.

**B-3 — Profiles + setup export.** *Gate:* profile editor composes a PR under the editing user's identity with the CL-Resolves trailer generated (F-5's lesson); no write path to main — asserted by test; one-click export serves A-2's download; bundle staleness visible.

**B-4 — Audit + Benchmarks.** *Gate:* auditor role exists server-side first (roles.yaml + profile), then the read-only audit view; benchmarks view renders scores per kb_ref **when they exist** — the view ships dark behind BASELINE-1 and says so, honoring §2.3 rather than inventing numbers.

**M5 gate:** every Part-5 inventory row is served, explicitly deferred with a trigger, or ruled out by the boundary list; every matrix cell reading "—" is a server 403/empty, not a hidden menu item.

## §5 Register calendar (decisions this phase owns)

- **SUPPRESS-1:** home is ruled (profile `limits.min_cell_count`, enforced at the publish path's re-validation, disclosed in the artifact). Build trigger: *first report with an audience beyond its author* — which B-1's demos may themselves trip; if outside viewers see reports before then, the build pulls forward into whichever checkpoint is current.
- **RA-F:** decision due 2027-01-31, or first push_limit_exceeded, or the second Power BI customer — whichever first. The A-0 telemetry warning is its tripwire.
- **RA-G + SO-G + RA-D:** one design conversation (report lifecycle/refresh/naming), at the first unretired report, first delete request, or second Power BI customer.
- **OB-5:** watch armed; load-bearing at the first customer with two execute-granted profiles; A-3/B-3 must not ship a second execute profile without the pairing check.
- **BASELINE-1 / MC-1 / OD-2 / MC-4 / SP-1 / FL-C:** unchanged triggers (first value-quoting conversation; recall table; first customer's first month of traffic).
- **Docker-heavy sync flake:** quarantine standard in force — next occurrence captured with full output before any re-run.

## §6 Risks → checkpoints

- **Boundary erosion** (a certify button, a merge button, a chart builder) — mitigated structurally: §2.5 is normative, B-1/B-3 gates assert the absences, and any exception is a ruling, never a patch.
- **Sequence temptation** (dashboard before knowledge floor) — accepted knowingly by §2.1, bounded by M4: Phase 2 cannot close on pixels; A-5 is a milestone condition, not a stretch goal.
- **Measurement debt** (BASELINE-1 deferred into an emergency) — mitigated by §2.2's booking rule and B-4 shipping dark rather than pressuring for numbers.
- **Solo-operator ceiling** — mitigated by A-2's second-human gate; their findings are recorded as first-user field notes, CP-8-style.
- **Silent-failure recurrence** (the D-84 class) — A-3's structural gate and B-1's SO-F consumption exist because this class already cost two silent days once.

## §7 Phase exit — CP-Ω

M4 + M5 closed; a phase retrospective in the CP-8 pattern (shorter): playbook re-grade, register sweep, and the go/no-go question restated for its real audience — *the next onboarding, assisted or not, with the evidence to say which.*
