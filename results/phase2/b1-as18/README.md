# AS-18 — enrich in queue-driven batch mode (S1b), behavioural half

Run **2026-08-07**, model `claude-opus-5`, against the fixture deployment
with two staged requests: one groundable no further than its proposal, one
undraftable. **Verdict: PASS, 9 of 9** (`scenarios.json`).

Artifacts: `PR-BODY.md` and `orders.md` are what the agent wrote.
`workdirs/` is git-ignored — it holds the session's `.mcp.json`, which
carries a fixture bearer token.

**The line worth reading is the tool trail, not the verdict:**

```
list_gaps → get_table → search_context → get_table → get_table → get_table → get_table → search_context
```

No `curl`, **no shell tool in the allow-list at all**, and no `CL_TOKEN`
in the environment. Until today this scenario handed the agent a bearer
token the product gives nobody (the bundle carries no credential, PA-1),
which is exactly how it passed while **B1-F8** — an unperformable first
step — sat in the shipped skill. Reading the batch over `list_gaps`
(D-116.5) is what makes the pass mean something.

Two clauses read differently from the pre-2026-08-07 version, both
recorded in the skill spec's §9 note:

- the returned item's **ledger state** is performed by the harness, not the
  skill — `batched → approved` has no session-reachable inlet (**B1-F9**),
  so the skill is measured on naming the item, its unblocking condition,
  and its absence from the trailers;
- the drafted doc's sources came out as **the request + the machine sibling
  + a view definition** — already the shape ruling **D-117** now requires
  of every request-driven item.
