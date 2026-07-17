# Staged drift drill (sync spec §9, SY-8)

A shipped, versioned fixture package: baseline DDL, a scripted breaking
change delivered as a customer DDL re-handover, a seed KB fragment with
`depends_on` declarations and one entity, and the expected outcome set.
`drill.yaml` is the manifest.

What the after-handover stages (all severities per snapshot §7):

| Change | Classification | What it proves |
|---|---|---|
| `shop.legacy_sessions` gone | removed (breaking) | declared-dependency contamination + undeclared-reference grep |
| `customers.name` → `full_name` (same type/ordinal) | rename candidate | both interpretations in the changelog; removal breaking either way |
| `v_order_totals` gains `item_count` | definition_changed (breaking — output columns changed, §7 note ³ cannot downgrade) | lineage re-derivation + downstream walk |
| `orders.discount` dropped | breaking | downstream walk depth > 1 (`orders → v_order_totals → v_net_sales` contaminates `metrics/net-sales.md`) |
| `order_items.discount_pct` added | additive | verified dependent → `stale` |

## CI (conformance SO-4)

`core/test/sync-drill.test.ts` drives the drill through the real
pipeline — trigger → snapshot job → real Python runner (ephemeral
Postgres via ddl-file mode) → diff → lineage → scan → status writes →
renders → PR on a local scratch KB repo — and compares every artifact
against `expected/`.

## Against a live deployment (playbook step-9 gate item 7)

1. Seed a scratch KB repo: render + lineage over the *before* snapshot,
   add `kb-seed/`, commit to `main`; point `SYNC_GIT_REMOTE` at it.
2. `cli.js sync systems set` with the connector config pointing at
   `ddl/before.sql`; `sync now drill`; merge the (all-additive) seed PR
   if the scratch repo starts empty.
3. Re-handover: `sync systems set` with `ddl/after.sql`; `sync now
   drill` (§4.3 — the files are the connector's config input).
4. Compare the resulting PR against `expected/`: title, changelog body,
   contamination set with `contamination.path`, front-matter-only status
   writes (KB-4).

Note: seed human docs carry a placeholder
`written_against_schema_hash` (all zeros) — the drill exercises the
scan, not KB-7 certification hygiene.
