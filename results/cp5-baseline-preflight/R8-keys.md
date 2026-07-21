# Baseline v1 — R8 condition keys + rig evidence (CP-5, D-76.5 / D-79.6)

Three localhost-bound cores, sync disabled on all three (D-75.4), one KB
each. Keys captured from `/healthz` (mechanical, not asserted).

| Condition | kb_ref | render hash | profile | remote (private?) | port |
|---|---|---|---|---|---|
| enriched-kb | `14fe1e60cee0c003ba104750ea4e85c1e939f9b4` | n/a (customer KB) | benchmark (full read+exec) | AlperCamli/DataAnalyticsTool (public) | 8100 |
| machine-kb | `af1469e0274cd4e8ab1c0d50661a44243a8d05fc` | `sha256:400e359d312a98613053966f8377f17f33af1c96efbe9c977d2f18392ffcf076` | benchmark (full read+exec) | AlperCamli/cl-baseline-machine-kb (**private**) | 8101 |
| no-kb | `456d8cc64cc7cb7bd61c516b719377fa7c38f897` | n/a (profiles only) | benchmark (validate+exec only, no content tools) | AlperCamli/cl-baseline-nokb (**private**) | 8102 |

The machine-kb render hash matches the CP-2 manual baseline's machine-kb
ref (`sha256:400e359d3…`) — deterministic, same snapshots → same render.

## Sync-disabled proof (D-75.4)

`/healthz` `instance.sync_enabled` was **False** on all three cores
(recorded in `packet.json`). They serve MCP + the gateway only; no
scheduler, webhook, or run loop. The production live stack remains the
sole sync writer.

## Smoke journey (D-77.4)

One benchmark journey, RB-01, enriched condition, **executed against the
live example Supabase** through the real gateway under the benchmark
profile — then STOP. `smoke-record.json`:

- tools: search_context → get_table → get_entity → validate_sql →
  execute_sql (×3). Loop completed: validate **and** execute.
- The agent grounded in the KB, validated, executed real SQL against
  `public.users`, and honestly reported the table is empty rather than
  fabricating a number.
- `cost_usd` 0.686 recorded, informational only (D-77).

## Fixture-side evidence (from results/cp5-scenarios/, D-74.4b/4c + D-75.1)

- **4b/4c**: `core/test/nokb-condition.test.ts` — no-kb validates against a
  real table with no roles.yaml; a roles.yaml without a benchmark entry
  fires a named audit signal (never silent attrition).
- **D-75.1 non-shadowing**: `core/test/compile.test.ts` — a skills/ dir in
  a KB is ignored by compilation; skills come from the core image.

## Teardown (D-76.3a)

Both `cl-baseline-*` repos and the three instances are torn down after
baseline v1 commits. Until then they stay private and localhost-bound.
