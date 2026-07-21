# CP-5 skill conformance scenarios — AS-9 / AS-10 / AS-12 (D-78 layer (b))

The **gate evidence** for the three behavioral conformance items. Unlike
the rule validators in `tools/skill_conformance.py` (which test the
checker over staged artifacts), these run a real skill in a real headless
Claude Code session against the fixture deployment (skill-spec §9) and
assert on the audit stream and the files the agent produced. Per ruling
D-78: *a conformance item may only be reported green on evidence that
could have failed if the behavior were absent.*

## Verdict

`scenarios.json` — both journeys PASS under `claude-opus-4-8`.

| Item | Journey | What was observed |
|---|---|---|
| AS-12 | enrich `shop.orders` | doc carries a one-line `purpose` + `column_purposes` for the 5 grounded columns; no body section restates a front-matter one-liner |
| AS-9 | enrich `shop.orders` | `discount` (the deliberately unanswerable column) is **absent** from `column_purposes` and recorded as a gap via `flag_gap` and a Warnings note — not guessed |
| AS-10 | report net sales | request resolves through `v_net_sales` (`agent_guidance: warn-user`); the journey validated **and** executed; the stale-doc warning travelled into the artifact's `semantics.trust_notes` |

**Profile note (D-79.2).** AS-10 runs under the **reporter** profile. The
fixture reporter was refreshed to carry `execute_sql:drill`, mirroring the
product Reporter that gained execution at CP-6/M2 — an earlier run used
steward because the fixture reporter was frozen at its M1 read+validate
shape. A watch-note is on file: fixture profiles track product profiles.
The interactive runner can occasionally time out `execute_sql` in the
ephemeral fixture; when it does, the skill discloses it honestly ("NO
RESULTS … timed out") rather than inventing numbers, and the AS-10
assertions (execution reached, warning in the artifact) still hold — the
disclosure is exactly the behavior under test.

Produced artifacts, committed verbatim as evidence:
- `enrich-orders.md` — the human doc the enrich skill wrote.
- `report-artifact.json` — the report artifact, trust_notes included.

## These tests can fail (the falsifiability point)

The AS-10 journey **failed** on its first run: the profile in use exposed
no `execute_sql`, so the loop stopped at validation and the "validated and
executed" assertion went red. That is the assertion discriminating exactly
as it should — the harness observes real behavior and fails when the loop
does not close. (Resolved by running the report journey under the steward
profile, which carries `execute_sql:drill`; the fixture's reporter profile
is the M1 read+validate one.)

Equally, the enrich AS-9 check would fail the moment the skill wrote a
plausible `discount` one-liner instead of flagging it — which is the whole
behavior under test.

## Re-run (D-78.3)

Cheap enough to be the norm on any skill edit; needs no example estate.

```
# 1. a throwaway postgres (or reuse the compose one at :5433)
docker run -d --name cl-fixture-pg -e POSTGRES_PASSWORD=postgres -p 55432:5432 postgres:16

# 2. stand the fixture up (keeps running)
make fixture-up ADMIN_DB=postgres://postgres:postgres@127.0.0.1:55432/postgres \
                FIXTURE=/tmp/cl-fixture.json

# 3. in another shell, run the scenarios
make scenarios FIXTURE=/tmp/cl-fixture.json
```

`claude` must be on PATH. Cost is the operating user's responsibility
(D-77); nothing here gates on it.
