# AS-19 — enrich in contamination-triage mode (S1c), behavioural half

Run **2026-08-07**, model `claude-opus-5`, against the fixture deployment.
**Verdict: PASS, 5 of 5** (`scenarios.json`). D-78 layer (b): this is the
conformance evidence for S1c; the validators in
`tests/test_skill_conformance.py` are regression tests and are not.

## What was staged, and why each class is decidable

Three contaminated docs (`tools/scenarios/triage-kb/`), one per class, each
settled by the staged snapshot and nothing else:

| Doc | Staged so that | Correct class |
|---|---|---|
| `shop/exports.md` | its enum decoding already matches the new `CHECK` exactly, on both constrained columns | `confirms-prose` |
| `shop/imports.md` | it calls four values "the whole vocabulary"; the `CHECK` admits six | `needs-re-grounding` |
| `shop/orders.md` | `depends_on` names `triage.shop.legacy_carts`, absent from the snapshot | `depends-on-missing-object` |

An agent that skimmed and stamped all three alike fails on the first
assertion. That is the point of the staging.

## What the run shows

All five assertions green: every doc classified correctly; `exports.md`
repaired **front-matter-only with a byte-identical body**; `imports.md`
re-grounded from the constraint and citing it at DDL grade; `orders.md`
left `contaminated` with its unresolved dependency intact; no
`status: verified` and no `last_verified` written anywhere; and the PR body
carrying the per-doc table and handing certification back to the steward.

**Tool trail: `(none)`.** S1c reads the working copy — contamination is
front-matter and the facts are in the KB's own accepted snapshot — so the
mode adds no MCP call and the scenario asserts on files rather than on the
audit stream. The MCP config was handed over regardless; the session chose
not to need it.

Two things the agent did that no assertion asked for, and both are the
behaviour the rules are trying to produce:

- it **declined to improve `exports.md`'s `sources` list** with the
  stronger `CHECK` citation, naming it as drafting under cover of a repair
  and leaving it for a batch that says that is what it is doing;
- it **refused to claim a green self-check**, reporting instead that the
  staged KB has no vendored wheel and no machine layer, and listing what it
  verified by hand in place of the CI gate. It also surfaced a genuine
  fixture defect — the staged snapshot was missing `system_class` and so
  failed schema validation. Fixed in the fixture; the run predates the fix,
  which is why the PR body still describes it.

## Falsifiability (D-78.2)

`falsify.py` takes these very artifacts and mutates them four ways, each a
real failure mode of the mode; `falsify-output.txt` is what came back:

1. a `confirms-prose` repair that also polished the prose → flagged;
2. the skill certifying its own repairs → flagged three ways per doc;
3. the orphaned doc turned green by deleting the dependency → flagged as
   removing the tripwire;
4. a PR body with the certification section removed → CP-E6.

Re-runnable: `.venv/bin/python results/phase2/a5/as19/falsify.py`.

## Artifacts

- `scenarios.json` — the harness record (assertions, session id, cost)
- `PR-BODY.md`, `exports.repaired.md`, `imports.repaired.md` — what the agent wrote
- `workdirs/enrich-triage/` — the full working directory as it was left
- `falsify.py`, `falsify-output.txt` — the D-78.2 demonstration

Re-run: `.venv/bin/python -m tools.skill_scenarios --connection <fixture.json>
--model claude-opus-5 --only enrich-triage --out results/phase2/a5/as19`.
