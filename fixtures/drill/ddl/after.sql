-- Drill fixture v1 — the scripted breaking change (sync spec §9), as a
-- customer DDL re-handover (§4.3: new files as the connector's config).
-- Versus before.sql:
--
--   1. DROP:             shop.legacy_sessions is gone            (breaking)
--   2. RENAME CANDIDATE: shop.customers.name → full_name — same
--                        type (text) and dense ordinal (3)       (breaking)
--   3. OUTPUT-CHANGING VIEW EDIT: reporting.v_order_totals gains
--                        item_count — definition + column set
--                        change, so §7 note ³ cannot downgrade   (breaking)
--   4. shop.orders loses discount (unused by any view)           (breaking,
--                        walks downstream to both reporting views)
--   5. shop.order_items gains discount_pct                       (additive →
--                        verified dependents go stale)

CREATE SCHEMA shop;
CREATE SCHEMA reporting;

CREATE TABLE shop.customers (
    id        bigint PRIMARY KEY,
    email     text NOT NULL,
    full_name text
);

CREATE TABLE shop.orders (
    id          bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES shop.customers (id),
    status      text NOT NULL DEFAULT 'new',
    net         numeric(12,2) NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shop.order_items (
    id           bigint PRIMARY KEY,
    order_id     bigint NOT NULL REFERENCES shop.orders (id),
    sku          text NOT NULL,
    qty          integer NOT NULL,
    price        numeric(12,2) NOT NULL,
    discount_pct numeric(5,2)
);

CREATE VIEW reporting.v_order_totals AS
SELECT o.id AS order_id,
       o.customer_id,
       sum(i.qty * i.price) AS items_total,
       count(i.id) AS item_count
  FROM shop.orders o
  JOIN shop.order_items i ON i.order_id = o.id
 GROUP BY o.id, o.customer_id;

CREATE VIEW reporting.v_net_sales AS
SELECT t.customer_id,
       sum(t.items_total) AS net_total
  FROM reporting.v_order_totals t
 GROUP BY t.customer_id;
