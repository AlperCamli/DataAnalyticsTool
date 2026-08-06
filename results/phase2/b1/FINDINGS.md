# B-1 findings

## B1-F1 — re-enqueue replayed a captured payload, so a pre-A-4 job could never succeed

**Found 2026-08-06 by the operator, on the gate runbook's act 3**, the
first time anyone pressed *Re-enqueue as me* on the pilot's real
dead-letter queue. Reported in three parts, which turned out to be one
fault and two of its symptoms.

### What was seen

> I clicked Re-enqueue as me, and it appeared like it goes to the running
> then immediately came back to the dead_lettered again. […] tracking the
> process of re-enqueue is not clear enough. Also, we have this in the
> queue, and create another dead lettered instance everytime I enqueue it:
>
> ```
> snapshot
> supabase · dead_lettered · attempt 1/5 · 0s ago
> auth_error credential reference 'env://SUPABASE_DSN': no resolver for
> its scheme (configured: vault://)
> ```

The chain was in the data:

| job | created | payload ref | outcome |
|---|---|---|---|
| `01KYW10ST…` | 2026-08-04 12:05 (**pre-A-4**) | `env://SUPABASE_DSN` | config_error |
| `01KZBD5CW…` | 11:26 | `env://SUPABASE_DSN` | auth_error |
| `01KZBD90G…` | 11:27 | `env://SUPABASE_DSN` | auth_error |
| `01KZBDF6C…` | 11:31 | `env://SUPABASE_DSN` | auth_error |

Meanwhile `sync_systems` holds
`vault://secret/contextlayer/connections/supabase#introspect_dsn`.

### The fault

**A job's payload is a *capture* of the connection registry, taken at
enqueue time. Re-enqueue replayed the capture.** So a job queued before
the A-4 vault migration carried the reference that used to be right, the
runner has had no `env` resolver since, and every press produced a fresh
dead job with the same impossible reference. The button could not have
worked, and pressing it harder made the queue longer.

This is the **fan-out rule** — the registry is the one source for what a
connection uses, and a captured copy that disagrees with it is not
evidence, it is a stale duplicate. It is also **A-4's removal rule from
the other side**: `env://` was removed as a resolver, and the job queue
turned out to be a place the old reference survived. A-4 found the same
shape in the G3 execution preflight (A4-F6); this is its sibling, and it
survived A-4 because nothing re-read old job payloads.

*Not* found by A-4's own checks, and worth saying why: every live
surface was green. The connection row was flipped and probed green, the
core resolved its config, five probes passed. The stale references were
in rows nobody reads until someone presses a button that had not been
built yet.

### Two symptoms, both real defects of their own

- **The pointer was in the wrong place.** The first cut wrote
  `error.reenqueued_as` onto the dead job — a success fact inside the
  field that says why the job died. The operator's phrasing ("the fault
  is written to the succeed but not erased from dead letters") is exactly
  what that looks like from outside.
- **Nothing followed the new job.** The UI answered "queued" and stopped,
  so the outcome had to be discovered by noticing a new row in a list the
  operator had just left. For a button whose whole purpose is to retry
  something, not reporting the retry's result is most of the feature
  missing.

### Fixed

1. **The payload is rebuilt from the current registration**, never
   replayed. The connection's stored `payload` is already
   `{config, credentials}` — the same shape a snapshot or probe job takes
   — so the substitution is clean rather than a translation. The
   connector name and version constraint come from the registration too.
2. **The response reports the difference** when the captured references
   and the current ones disagree, because the operator is about to see a
   different outcome from the same button and the reason belongs in the
   answer.
3. **No registration → refused**, with the reason: running a
   configuration the estate no longer has would prove nothing.
4. **`execute` and `publish` are refused.** Their payloads are not the
   registry's to rebuild — they carry a person's statement, their
   identity and the guardrails they were granted. Re-running one means
   re-running somebody else's request under their recorded identity with
   nobody waiting for the answer; for publish it would re-deliver a
   report to a BI tool because an operator was clearing a queue. The line
   is *whose request the payload holds*, not batch-vs-interactive.
5. **A second press on the same dead row is a 409** naming the successor.
   Three presses produced three parallel branches from one stale point;
   the chain continues from the newest job or not at all.
6. **`reenqueued_as` is its own column** (migration 0014), with the
   existing rows moved out of `error` rather than left behind.
7. **The UI follows the new job** to a terminal state and reports it in
   place — including "it failed too, read this before pressing anything
   else" — and renders the chain on the dead row.

### Tests

`core/test/dashboard-b1.test.ts`, five of them, staged in the pilot's own
shape: a dead job carrying `env://GONE_SINCE_THE_MIGRATION` against a
connection registered at `vault://…`. Asserted: the new job's payload
carries the current reference and contains no `env://` anywhere; the
response reports captured-vs-current; a second press 409s with the
successor's id; an unregistered system refuses; an `execute` job refuses
with the reason. Each fails with the old behaviour.

### What it says about the runbook

Act 3 said "press Re-enqueue as me" as if the interesting part were the
button. On this estate the interesting part was that the button exposed
a stale-reference tail A-4 left behind. The act is rewritten to say so,
and to have the operator read the captured-vs-current line rather than
watch for a state change.
