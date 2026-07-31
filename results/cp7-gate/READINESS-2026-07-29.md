# M3 gate demo — readiness report, 2026-07-29 (post-D-94)

Session scope: apply ruling D-94, author the two KB pull requests, gather
the certification evidence, prepare machine 1. **No demo execution.**

> **Note on the a–g table.** The prep report's a–g table exists only in
> the July 29 prep session's output, not as a file in the repo. It is
> reconstructed below from the seven runbook §3 prerequisites that were
> not `done` at the time — the same seven items, same order.

---

## VERDICT: **NO-GO**

One blocking defect, found during this session's prep and **not fixable
inside D-94's fence**. Everything else on the list is green.

### The blocker — the runner does not host the Power BI connector

`deploy/runner-config.yaml` lists five connectors: `static_demo`,
`postgres`, `ga4`, `gsc`, `looker_studio`. **`connectors.powerbi.connector`
is not among them.** Verified after a clean `docker compose build core
runner` and restart today:

```
runner runner-local: hosting static-demo@0.1.0, postgres@0.2.0,
                     ga4@0.2.0, gsc@0.2.0, looker_studio@0.1.0
```

Why it stops Act 1: `publish_report` (both `deliver_model` and `attest`)
enqueues a `publish` job whose connector name comes from the registration
— `powerbi` — and the SDK service only claims job types for connectors
loaded from its config file (`declared_connectors()` iterates
`self.connectors`). A connector nobody declares is a job nobody claims,
so the deliver call waits out its interactive deadline and returns an
`upstream_error`. Act 1 dies at the first publish, Act 2 with it.

Why it was never caught: the July 29 live verification
(`tests/test_powerbi_live.py`) drives the publisher **directly**, by
design — its own docstring says "the full MCP-server path is
fixture-proven and demo'd at the gate". The fixtures use a fake runner
that hosts whatever the test declares. So the one path that has never run
end-to-end is exactly the one the gate demo takes. The ops DB confirms
it: `jobs` holds three `publish` rows, all `looker_studio`, none
`powerbi`.

**Recommended fix (yours to authorize — one line + a restart):** add
`- connectors.powerbi.connector:connector` to `deploy/runner-config.yaml`'s
`connectors:` list, restart with runbook 4.3, and confirm the startup
line names `powerbi`. The runner already holds `POWERBI_CLIENT_SECRET`
(step 4.2, verified today), and the registration already carries the
credential *reference* and the `publish.flags` block, so nothing else
needs to move.

**Recommended verification before the demo, not during it:** one
`deliver_model` + `attest` against the existing fixed artifact id
(`ra-live-powerbi-jobs-0001`, so it revises rather than litters) driven
through the MCP surface as the reporter. That is the assertion this
session cannot make and the demo should not be the first to test.

I did not make the change: D-94.4 authorizes exactly one line, in
`docker-compose.yml`, and the scope fence says a defect needing more code
is flagged, not fixed.

---

## The a–g table, re-run against current state

| | Prerequisite | State | Evidence |
|---|---|---|---|
| **a** | Platform stack rebuilt with the Power BI leg (4.1) | **PASS** | `npm run build` + `docker compose build core runner` clean; stack restarted and healthy |
| **b** | Publish budget raised for the demo window (4.3) | **PASS** | `CORE_MCP_PUBLISH_PER_HOUR=12` read back off `dataproject-core-1`. The passthrough is now declared in `docker-compose.yml` (D-94.4) with a test that fails without it |
| **c** | GA4 + Search Console registered on the stack (4.4b) | **PASS** | Five systems registered; `ga4`, `gsc`, `supabase` query-capable, `powerbi`/`looker_studio` not. One live gateway execution each: GSC 21 rows, GA4 78 rows, both `allowed` in the audit trail, both claimed by the runner (`connector=gsc`, `connector=ga4`) |
| **d** | Reporter profile allows Power BI publishing | **PASS** | KB PR #28 merged; `publish_report:powerbi` on `origin/main`. The trailer closed gap `6473a5f1` by itself: `resolved / pr / pull/28` — and PR #27, merged from the same branch **without** the trailer, did not close it. `results/cp7-gate/l5-loop-closure/` |
| **e** | Reporter bundle rebuilt after that merge (4.7) | **PASS** | Compiled after the merge; `CLAUDE.md` lists `publish_report:looker_studio` **and** `publish_report:powerbi`; four files present; `pbir_tool.py` sha256 `b3f73a04…`. Staged at `~/reporter-setup`, **not yet copied to machine 2** |
| **f** | `entities/page.md` certified | **FINDING — operator's call** | Evidence gathered through the gateway; the doc's stated `path()` rule **fails on the homepage** (see below). KB PR #29 drafted with the fix + proposed flip, **not merged**. `results/cp7-gate/page-certification/` |
| **g** | Machine 2 has Python 3 | **UNVERIFIED — machine 2** | Cannot be checked from here; runbook 5.4 |

Plus the item that was not on the original list:

| | | | |
|---|---|---|---|
| **h** | Runner hosts the `powerbi` connector | **FAIL — blocker** | See above |

---

## STOP-2 — the certification finding, in one paragraph

The mapping in `entities/page.md` is right: Search Console reports a full
URL, GA4 reports a path, and they address the same pages — 20 of 21
Search Console pages matched. The **normalization rule** is wrong.
"Strip a trailing slash", written without an exception, turns the
homepage `https://example-estate.com/` into the empty string while GA4
reports it as `/` — **195 views, the busiest page in the estate, more
than four times the next**. The join drops it silently and returns 20
healthy-looking rows. PR #29 adds the root carve-out and re-verifies:
21 of 21 match. Per D-94.5 this is a finding, so nothing was flipped on
the doc as it stands; the PR proposes `status: verified` on the *fixed*
rule and is yours to judge.

If you decline the fix, **Act 2 runs in its negative-only variant**: the
blend cannot cite a certified document, so the act demonstrates the
refusal (uncertified source) rather than the documented-join success.

---

## What this session changed

Platform repo (commit `9df9b45` and this one):

- `DECISIONS.md` — D-94 verbatim; correction notes appended under D-93
  for flags ② and ③ (history appended, never rewritten).
- Register: **SO-G** (GA4/GSC refresh cadence under an api-class target),
  **RA-G** (report lifecycle/teardown), **PA-2** (compiled-bundle
  staleness, filed beside PA-1, its home design).
- `docker-compose.yml` — the `CORE_MCP_PUBLISH_PER_HOUR` passthrough, and
  `tests/test_compose_env_passthrough.py`, which reads the value back out
  of `docker compose config` and fails on all three assertions with the
  line removed.
- Runbook — 4.3 simplified; Act 3a's two-shape pass criterion, coaching
  ban and optional probe (the probe was dry-run: it returned
  `permission_denied` and wrote a real `denied` audit row).
- Evidence: `page-certification/`, `l5-loop-closure/`, this report.

KB repo: PR #28 (merged, the grant), PR #29 (open, the certification).

## Suites

- Python: **724 passed, 14 skipped** — includes the three new read-back
  assertions.
- Core: **185 passed across two consecutive full runs** on an otherwise
  idle machine — D-92.3's accepted evidence standard, met. Four earlier
  runs today did fail, and honestly: two `e2e.test.ts` lease-expiry
  timeouts and one `property.test.ts` `deferJob` transaction failure,
  every one of them while another suite or docker work was running
  alongside. That is the known load-sensitive class on JC-4's watch item,
  not a regression from this session's one-line change — the same runs
  were green the moment the machine was quiet, and the changed file is a
  compose declaration no test in that set reads.
