# CVBuilder benchmark — manual-baseline report

- **suite** `cvbuilder` v0 · **journey-prompt** v1 · **backend** `claude-code-interactive` · **model** `claude-opus-4-8`
- **reps** 1 · **journeys** 5 · **GA4 executions** 2
- **snapshot_refs** ga4 `sha256:9f220827b`, gsc `sha256:0cbb22740`, supabase `sha256:ed698942e`
- **kb_refs** no-kb `live-discovery`, machine-kb `sha256:400e359d3`, enriched-kb `ccda04f499fc056e`
- **window** 2026-07-16T10:32:07.612777+00:00 → 2026-07-16T10:32:07.617160+00:00
- _R6 executable = first-try execution success; refines to validate-pass when validate_sql lands (CP-4). Manual transport: interactive Claude Code sessions per OPERATOR.md; prompt file benchmark/prompts/journey-prompt-v1-manual.md (v1 variant); tokens/cost null (unmeasurable); tool_calls = executor calls only._

## Three-condition comparison (mean · range)

| Condition | n | Selection precision | Selection recall | First-try executable | Result correctness |
|---|---|---|---|---|---|
| no-kb | 2 | 0.75 · 0.50–1.00 | 0.60 · 0.20–1.00 | 1.00 · 1.00 | 0.00 · 0.00 (n=2) |
| machine-kb | 1 | 1.00 · 1.00 | 1.00 · 1.00 | 1.00 · 1.00 | 0.00 · 0.00 (n=1) |
| enriched-kb | 2 | 0.72 · 0.44–1.00 | 0.90 · 0.80–1.00 | 1.00 · 1.00 | 0.00 · 0.00 (n=2) |

## MC-1 retrieval recall (per-journey selection recall)

Recall of each case's `expected_objects` in the agent's executed statement(s). This is MC-1's metric (lexical retrieval, no embeddings — MC-1 default).

| Case | no-kb | machine-kb | enriched-kb |
|---|---|---|---|
| RB-01 | 1.00 | 1.00 | 1.00 |
| RB-04 | 0.20 | — | — |
| RB-05 | — | — | 0.80 |

## Per-case breakdown

| Case | Condition | Precision | Recall | Exec | Correct | Divergence |
|---|---|---|---|---|---|---|
| RB-01 | no-kb | 1.00 | 1.00 | 100% | 0% | supabase shape (2, 11)≠(2, 6) |
| RB-01 | machine-kb | 1.00 | 1.00 | 100% | 0% | supabase shape (2, 4)≠(2, 6) |
| RB-01 | enriched-kb | 1.00 | 1.00 | 100% | 0% | supabase shape (2, 4)≠(2, 6) |
| RB-04 | no-kb | 0.50 | 0.20 | 100% | 0% | ga4 shape (2, 2)≠(5, 0) |
| RB-05 | enriched-kb | 0.44 | 0.80 | 100% | 0% | ga4 shape (4, 12)≠(4, 6) |

## FM-2 evidence — visual_kind coverage

- Five-kind registry (formats spec, FM-2): `table`, `line`, `bar`, `scorecard`, `pivot`
- Registry kinds exercised: 5/5 — `table`, `line`, `bar`, `scorecard`, `pivot`
- `other:*` used: `other:funnel`
| Case | visual_kind |
|---|---|
| RB-01 | `line` |
| RB-02 | `pivot` |
| RB-03 | `table` |
| RB-04 | `pivot` |
| RB-05 | `bar` |
| RB-06 | `pivot` |
| RB-07 | `other:funnel` |
| RB-08 | `scorecard` |
| RB-09 | `line` |
| RB-10 | `scorecard` |

## SP-4 / FM-4 evidence — recurring cases

- `recurring: true` count: **10** of 10 — RB-01, RB-02, RB-03, RB-04, RB-05, RB-06, RB-07, RB-08, RB-09, RB-10
- SP-4/FM-4 default: saved/parameterized re-runs are out of v1 (re-run = re-journey). Every case here is a recurring reporting need, so the suite exercises the re-journey path that SP-4 leaves as the v1 answer.

