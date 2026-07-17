## Breaking

- `drill.reporting.v_order_totals` — definition_changed
  - contaminates `metrics/net-sales.md` (lineage path: `sha256:b6b4ccf14588…`)
  - contaminates `systems/drill/reporting/v_net_sales.md` (declared dependency)
- `drill.shop.customers` — column_removed: name
  - contaminates `entities/customer.md` (declared dependency)
  - contaminates `systems/drill/shop/customers.md` (declared dependency)
- `drill.shop.legacy_sessions` — object removed from snapshot
  - contaminates `systems/drill/shop/legacy_sessions.md` (declared dependency)
- `drill.shop.orders` — column_removed: discount; column_ordinal_changed: created_at
  - contaminates `metrics/net-sales.md` (lineage path: `sha256:3ffcb89caadd…` → `sha256:b6b4ccf14588…`)
  - contaminates `systems/drill/reporting/v_net_sales.md` (lineage path: `sha256:3ffcb89caadd…`)
  - contaminates `systems/drill/shop/customers.md` (declared dependency)

### Rename candidates

- `drill.shop.customers`: `name` → `full_name` (type text, ordinal 3) — either **column renamed** or **column removed + column added**; the removal is breaking under both readings

## Additive

- `drill.shop.order_items` — column_added: discount_pct

## Docs marked stale

- `systems/drill/shop/order_items.md` (additive drift on `drill.shop.order_items`)

## Undeclared possible references

Body-text mentions of changed objects in docs that do not declare them —
surfaced for review, never auto-flagged (KB §6 step 5).

- `systems/drill/reporting/v_net_sales.md` mentions `drill.shop.legacy_sessions`
