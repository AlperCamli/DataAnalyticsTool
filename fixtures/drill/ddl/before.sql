-- Drill fixture v1 — baseline schema (sync spec §9, ruling F2/SY-8).
-- Executed by real Postgres via the postgres connector's ddl-file mode.

CREATE SCHEMA shop;
CREATE SCHEMA reporting;

CREATE TABLE shop.customers (
    id    bigint PRIMARY KEY,
    email text NOT NULL,
    name  text
);

CREATE TABLE shop.orders (
    id          bigint PRIMARY KEY,
    customer_id bigint NOT NULL REFERENCES shop.customers (id),
    status      text NOT NULL DEFAULT 'new',
    net         numeric(12,2) NOT NULL,
    discount    numeric(12,2),
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shop.order_items (
    id       bigint PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES shop.orders (id),
    sku      text NOT NULL,
    qty      integer NOT NULL,
    price    numeric(12,2) NOT NULL
);

CREATE TABLE shop.legacy_sessions (
    id         bigint PRIMARY KEY,
    visitor_id text NOT NULL,
    started_at timestamptz NOT NULL
);

CREATE VIEW reporting.v_order_totals AS
SELECT o.id AS order_id,
       o.customer_id,
       sum(i.qty * i.price) AS items_total
  FROM shop.orders o
  JOIN shop.order_items i ON i.order_id = o.id
 GROUP BY o.id, o.customer_id;

CREATE VIEW reporting.v_net_sales AS
SELECT t.customer_id,
       sum(t.items_total) AS net_total
  FROM reporting.v_order_totals t
 GROUP BY t.customer_id;
