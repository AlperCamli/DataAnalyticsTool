# M3 gate demo — runbook (CP-7 part B)

The live run that closes M3. Fixtures proved the code; only this passes
the gate. Machine 1 is the platform host (this repo, the stack, the
estate); machine 2 is the reporter's laptop and sees nothing but an MCP
URL and a login.

Everything under "already done" was verified on 2026-07-27 — re-check it
rather than redo it.

---

## Already done (do not redo)

| Prerequisite | State |
|---|---|
| Task 7.0 views applied (definer + barrier, D-81) | live; `contextlayer_exec` has SELECT on all five |
| Drift PR #25 | merged — machine docs + lineage edges for all five views |
| Enrichment PR #26 | merged — human semantics for all five, `0 errors, 0 warnings` |
| KB PR #23 | merged — reporter carries `publish_report:looker_studio`, confirmed in the live server's `tools/list` |
| `looker_studio` connection | registered in `cl_ops.sync_systems`, template `00000000-0000-0000-0000-000000000000`, five visual kinds |
| Credential rotation (D-84.1) | both halves done and verified — LAN exposure is authorized |
| QE-5 encoding + runner isolation (D-85) | landed; dates come back as ISO text instead of killing the runner |

## Machine 1 — host preparation

The stack is up and bound to the LAN as of this writing. Confirm rather
than restart:

```bash
curl -s http://192.168.1.4:8100/healthz            # mcp_enabled + sync_enabled true
docker compose logs runner | grep -i "execution preflight" | tail -1
```

Expected: `execution preflight passed for postgres: {'role': 'contextlayer_exec', …}`.
A **FAILED** line means the runner is withholding execution (G3 doing its
job) and every execute job will hang to its deadline — fix before demoing.

If it needs bringing up again:

```bash
cd ~/Desktop/DataProject
set -a; . .secrets/sync.env; set +a
SYNC_PLATFORM_COMMIT=$(git rev-parse HEAD) CORE_MCP_ENABLED=1 \
CL_BIND=0.0.0.0 CL_HOST_ADDR=192.168.1.4 \
  docker compose -f docker-compose.yml -f deploy/compose.live.yml up -d
```

`CL_BIND=0.0.0.0` makes the ports reachable from machine 2; `CL_HOST_ADDR`
makes the OAuth issuer resolvable there. Getting the second one wrong
shows up as a login that redirects to `localhost` and hangs. Sourcing
`sync.env` is not optional — compose ranks `environment:` above
`env_file:`, so an unexported file silently disables sync (D-84.2).

**Note the demo start time in UTC before machine 2 begins** — the
evidence extractor takes it as its window:

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
```

## Machine 2 — setup (one line)

**Machine 2 is not a Mac** (Linux/Windows), so the delivery step is a
plain HTTP fetch — AirDrop, `pbpaste` and macOS Sharing do not apply,
and `scp` fails with "connection refused" because Remote Login is off on
machine 1 by default (verified 2026-07-27: the host pings and the demo
ports answer regardless — `sshd` and Docker's published ports are
unrelated services).

First, confirm machine 2 can reach the platform at all:

```bash
curl -s http://192.168.1.4:8100/healthz     # expect mcp_enabled + sync_enabled true
```

Then hand the `report` skill across. It is a single 13232-byte file in
this repo, which has no remote (D-82). **On machine 1**, for the length
of the fetch only:

```bash
python3 -m http.server 8200 --directory ~/Desktop/DataProject/core/skills/report
```

**On machine 2** — Linux, or Windows under WSL/Git Bash:

```bash
mkdir -p ~/cp7-demo/.claude/skills/report && curl -fsS http://192.168.1.4:8200/SKILL.md -o ~/cp7-demo/.claude/skills/report/SKILL.md && cd ~/cp7-demo && claude mcp add --transport http context-layer "http://192.168.1.4:8100/mcp?profile=reporter"
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force "$HOME\cp7-demo\.claude\skills\report" | Out-Null
curl.exe -fsS http://192.168.1.4:8200/SKILL.md -o "$HOME\cp7-demo\.claude\skills\report\SKILL.md"
cd "$HOME\cp7-demo"
claude mcp add --transport http context-layer "http://192.168.1.4:8100/mcp?profile=reporter"
```

Stop the server on machine 1 (`Ctrl-C`) once the file has landed. Verify
it arrived whole — **13232 bytes** (`wc -c` / `(Get-Item …).Length`). A
truncated skill is worse than none: the session would half-follow the
procedure, and the grounding discipline is precisely what this gate
tests.

If you would rather open no port at all, any USB volume or shared drive
works — the file just has to end up at
`~/cp7-demo/.claude/skills/report/SKILL.md`, with `claude mcp add` run
separately.

Then `claude` in `~/cp7-demo`. A browser opens for the dev IdP: log in as
**`reporter` / `reporter-dev-pw`**. Tokens last one hour; if the session
outlives that, re-authenticate rather than debugging odd 401s.

The login needs a desktop browser **on machine 2** — the redirect goes to
`http://192.168.1.4:8180`, which only resolves on the LAN. On a headless
Linux box, copy the printed authorize URL into a browser on any machine
that can reach that address; the callback returns to machine 2's local
listener, so a fully headless host without port forwarding will not
complete the flow.

`~/cp7-demo` is deliberately **outside** any clone of this repo. A
session started inside it would inherit the platform's `CLAUDE.md` and
stop being a customer-agent demo (the CP-2 contamination lesson).

---

## Act 1 — the happy path (B.1)

Seed case **RB-01** (signups by day, `line`), which is the smoke-journey
case and now runs through `reporting.v_user_signups_by_day`.

Prompts, in plain language — do not name the view, that is the point:

1. *"What do we know about user signups over time?"*
   → `search_context` / `get_table`. **Point at the trust block**: status,
   last verified, `snapshot_ref`. The view now carries the semantics from
   PR #26, including the warning that zero-signup days are absent.
2. *"Give me daily new signups for the last 90 days."*
   → `validate_sql` returns `verdict: pass` **and a validation token**,
   then `execute_sql` returns **real rows** — `signup_day` as
   `"2026-07-23"`, ISO text with `columns[].type = "date"`.
   **This is the M2 blocker gone**: RLS emptiness no longer applies to
   viewed data.
3. *"Publish that as a Looker Studio report."*
   → `publish_report`, `mode: template_link`, one `created[0]` of type
   `template_link` with a URL, plus `pending_human_steps`.

**Open the link.** This is the only check on the Linking API parameter
names, which are externally owned facts pinned in
`connectors/looker_studio/publisher.py` (`_SOURCE_PARAMS`, D-83.3).

**Record, per source alias:** did Looker pre-fill the data source, or did
it ask you to complete a field? A drifted name degrades softly — the
human fills that field in the UI, which template-link journeys require
anyway — so a prompt is not a failure, but **which** field prompted is
the finding. Note it verbatim; it goes in the gate note and the FM-2
record.

Also record which of the five declared visual kinds the template
actually exercised (`table`, `line`, `bar`, `scorecard`, `pivot`) — FM-2
wants the real answer, not the declared one.

## Act 2 — a documented cross-source blend (B.2)

**Read the flag below before running this act — it does not work as
originally specified, and the reason is the KB being honest.**

Use the page entity, which is the one documented cross-source join in
this KB: `entities/page.md` maps `gsc.standard.page` (key `page`) and
`ga4.standard.pagePath` (key `pagePath`).

*"Compare search impressions and pageviews for our top landing pages,
blended by page."*

Expect: two backings (GSC + GA4), a `blend` whose single key is
`left_column: page` / `right_column: pagePath` with
`entity_ref: entities/page.md`, and a publish that **succeeds**. Neither
leg is executed — the reporter may only execute against supabase, and
Looker pulls GA4/GSC itself through the template's own aliases. The
artifact is still validated end to end (F-7, token-less).

Point at: the blend key came from the entity doc, not from the agent's
judgement, and `entity_ref` resolves to a doc the reviewer can open.

## Act 3 — live denials (B.3)

Both must be **refused by the server and audited**, not talked out of by
the agent.

**3a — a target outside the profile.** *"Publish that same report to
Google Sheets instead."*
Expect `permission_denied`: the profile grants
`publish_report:looker_studio` and nothing else, the denial is
server-side, and it lands in `audit_records` with `decision = denied`.
The agent should say so plainly without speculating about targets it
cannot see (M-3).

**3b — an undocumented blend key.** Seed case **RB-08**
(GA4 purchases vs Supabase subscriptions). *"Blend the GA4 purchase
count with our new subscriptions so I can see them per transaction."*
Expect a refusal naming the entity doc and its documented key set —
`entities/conversion.md` documents `maps[].keys` of exactly `{id}`
(subscriptions' PK), and the GA4 objects carry none — followed by
`flag_gap(kind: missing_join_path)`. The ledger entry is the evidence;
an inline refusal alone does not close this act.

This is the KB refusing to invent a join that does not exist:
`entities/conversion.md` states outright that no shared row-level key
exists between a GA4 conversion and a subscriptions row.

## Act 4 — evidence (B.4)

Back on machine 1, with the start time noted earlier:

```bash
results/cp7-gate/extract-audit.sh '<demo-start-utc>'
```

Writes `audit-chain.txt`, `audit-chain.json`, `ledger-events.txt`,
`publish-results.json` beside the script — direct dumps of what the
server recorded, not a summary. Check before committing:

- the chain is continuous and every row carries `subject = reporter`;
- Act 1 shows `validate_sql` → `execute_sql` → `publish_report`, all
  `allowed`, with the executed statement text stored;
- **two** `denied` rows for Act 3a and the Act 3b refusal;
- `ledger-events.txt` contains the `missing_join_path` event with its
  `audit_ref` pointing back into the chain.

Then add the working Looker URL, the Linking API observations, and the
exercised visual kinds to the gate note.

---

## Flags — read before running

**1. Act 2 cannot be a seed case, and that is the KB working correctly.**
The gate asks for "a cross-source seed case published with its blend on
documented entity keys". The seed packet's only cross-source cases are
RB-05 (gsc+ga4+supabase, `entities/user.md`) and RB-08 (ga4+supabase,
`entities/conversion.md`) — and both entity docs state that no shared
row-level key exists: `user.md` maps only `supabase.public.users`
because GA4/GSC see anonymous visitors, and `conversion.md` says "there
is no documented blend key" in as many words. The packet itself
classifies both as `aggregate-reconciliation`, not joins. So a seed case
with a documented blend does not exist to run. The runbook above splits
the requirement: Act 2 demonstrates the documented blend using
`entities/page.md` (off-packet but real), and Act 3b turns RB-08 into
the refusal evidence it can honestly provide. If you would rather keep
Act 2 strictly on-packet, the alternative is to publish RB-08 **without**
a blend — two backings side by side, which is what a reconciliation is —
and accept that the blend-key path is then only demonstrated negatively.

**2. "Certified entity docs" do not exist yet.** All three entity docs
are `status: draft`, `last_verified: null` — batch 3 landed them that
way deliberately, since no mapping had been customer-certified. So Act 2
resolves `entity_ref` to a **draft** doc, and the artifact must not claim
`certified: true` (MT-10 refuses certification the KB never granted —
which is itself worth demoing if you want a third denial). To satisfy
the gate's wording literally, certify `entities/page.md` first: set
`status: verified` + `last_verified` via a KB PR. That is a human
certification act and is yours, not mine.

**3. The seed packet repeats the corrected `ai_runs.status` claim.**
`benchmark/suite/benchmark-seed-v0.yaml` (the `known_gaps` block) still
says `ai_runs.status` is ungrounded free text with no DB CHECK — the
same error D-86.3a corrected in `deploy/reporting-views.sql` and D-81.
I did not touch it: editing the seed packet changes the frozen input
BASELINE-1 will be measured against, and that trade-off is yours. It has
no effect on this demo — the reporter grounds against the KB, which now
publishes the enforced `pending | completed | failed` enum.
