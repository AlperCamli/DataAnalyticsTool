# Interrupted M3 gate demo — unplanned evidence (2026-07-29)

Kept and committed per ruling **D-93.1**. This is not a scripted act of
the gate demo: it is the record of a demo attempt that stopped early,
retained because what it caught is worth more than a clean re-run.

**Window:** `2026-07-29T09:13:55Z` → `09:21:05Z`, reporter profile,
machine 2 against the live stack on machine 1.

**Why it stopped:** the reporter profile carried no Power BI publish
grant at run time — prerequisite #1 of the runbook. The KB pull request
adding `publish_report:powerbi` to `.contextlayer/profiles/reporter.yaml`
had not been merged (and, as of this writing, has not been authored).

## What it demonstrates

**1. An ungranted api-class publish target did not produce a report.**
The agent recognised it held no Power BI target and said so, rather than
improvising a route. Read the gap description in `ledger-events.txt`
(09:21:05) — it names the grant it has, names the flow it therefore
cannot run, and asks who *does* hold the target.

*Be precise about this one.* The audit chain in the window contains **no
`publish_report` call at all**. The refusal was taken by the agent from
its compiled allow-set (`CLAUDE.md` lists `publish_report:looker_studio`),
not returned by the server as a `denied` row. The server-side gate is
real and independently evidenced — the same `audit_records` table holds
`execute_sql` denials from 2026-07-20 and 2026-07-27 ("tool execute_sql
is granted only for supabase, not ga4") — but it is not what stopped
*this* request. Described as "refused server-side", this run would be
claiming evidence it does not hold.

**2. `capability_gap` 6473a5f1 was filed and routed.** Kind
`capability_gap`, `routed_to: data-team`, `occurrences: 1`,
`distinct_subjects: 1`, status `open`, `audit_ref` linking back to the
call that raised it. Its L-5 lifecycle fields (`resolved_at`,
`resolved_by`, `resolution`) are still null — which is what makes it
usable as a live demonstration of loop closure when the grant PR merges
carrying the trailer.

**3. The design spine was applied unprompted to a dataset nobody
scripted.** At 09:19:28 the agent was asked for AI token usage and
refused to fake a daily trend: the finest available grain is month ×
provider, and deriving a daily figure as total ÷ calendar days "loses
per-day variance and cannot show a trend line". It filed the gap and
requested a `reporting.v_ai_tokens_by_day` view. Nothing in the runbook
mentions token usage — this is the honesty rule holding on unrehearsed
ground, which is the only place it counts.

**4. CP-R4 was held against an operator publish request** — per D-93.1.
This one is **not** evidenced by the files here. CP-R4 is a
conversational checkpoint; only the session transcript shows it. See
below.

## Files

| File | What it is |
|---|---|
| `audit-chain.txt` | Every MCP call in the window, as the server wrote it (same columns as `extract-audit.sh`): 17 rows — KB reads, three `validate_sql`, three `execute_sql` returning real rows, two `flag_gap`. No `publish_report`. |
| `ledger-events.txt` | The two fault-ledger events, with their issue status and routing. |
| `ledger-issue-6473a5f1.json` | Issue 6473a5f1 in full, including the null resolution fields. |

## What is missing

**The session transcript from machine 2 is not on machine 1** and was
not recoverable here. It is the only evidence for demonstration 4, and
the only human-readable account of 1 and 3. D-93.1 keeps it as gate
evidence; it still needs to be pasted in and committed alongside these
files. Drop it here as `transcript.md`.

D-93.1 also directs field notes to `DECISIONS.md`. Those are the
operator's to write — they watched the session; this directory only
holds what the server recorded.
