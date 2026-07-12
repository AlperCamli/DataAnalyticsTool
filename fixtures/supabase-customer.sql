-- Customer estate DDL, reconstructed from fixtures/supabase-ddl.json's
-- structural facts (the §8.2 record of the demo customer's estate) under
-- ruling D-44: the customer DDL files were never checked in, and the
-- task-1.9 exit evidence must run against a connector-produced snapshot
-- (qualified view definitions, the D-19.2 primary path). Regenerate the
-- snapshot with:
--
--   .venv/bin/python -m connectors.sdk.local connectors.postgres.connector \
--       --config <config with mode=ddl-file, image=postgres:15, this file> \
--       --out fixtures/supabase-customer.json
--
-- image postgres:15 per D-20 (customer 2 is Supabase 15.x; the fixture
-- envelope records server_version 15.8).

CREATE TABLE public.users (
    id uuid NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    email text NOT NULL UNIQUE,
    full_name text,
    created_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);
COMMENT ON TABLE public.users IS 'Registered accounts. Rows are soft-deleted via deleted_at.';
COMMENT ON COLUMN public.users.email IS 'Lowercased at the application layer; citext migration pending.';
COMMENT ON COLUMN public.users.deleted_at IS 'Soft-delete marker; NULL means active.';

CREATE TABLE public.orders (
    id bigserial PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES public.users (id),
    status text NOT NULL DEFAULT 'pending',
    total_cents integer NOT NULL,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.orders IS 'One row per checkout; immutable after payment settles.';
COMMENT ON COLUMN public.orders.status IS 'pending | paid | cancelled | refunded';
COMMENT ON COLUMN public.orders.total_cents IS 'Grand total in cents, tax included.';

CREATE TABLE public.products (
    id bigserial PRIMARY KEY,
    sku text NOT NULL UNIQUE,
    name text NOT NULL,
    price_cents integer NOT NULL,
    discontinued_at timestamptz
);
COMMENT ON COLUMN public.products.price_cents IS 'Current list price in cents.';

CREATE TABLE public.order_items (
    id bigserial PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES public.orders (id),
    product_id bigint NOT NULL REFERENCES public.products (id),
    quantity integer NOT NULL DEFAULT 1,
    unit_price_cents integer NOT NULL,
    UNIQUE (order_id, product_id)
);
COMMENT ON COLUMN public.order_items.unit_price_cents IS 'Price at time of purchase; the product price may change later.';

CREATE VIEW public.v_daily_revenue AS
SELECT date_trunc('day', o.created_at) AS day,
       sum(o.total_cents) AS revenue_cents,
       count(*) AS order_count
FROM public.orders o
WHERE o.status = 'paid'
GROUP BY 1;
COMMENT ON VIEW public.v_daily_revenue IS 'Paid revenue per calendar day. Used by the Looker Studio P&L page.';

CREATE MATERIALIZED VIEW public.mv_user_ltv AS
SELECT o.user_id,
       sum(o.total_cents) AS ltv_cents,
       min(o.created_at) AS first_order_at,
       max(o.created_at) AS last_order_at
FROM public.orders o
WHERE o.status = 'paid'
GROUP BY o.user_id;
COMMENT ON MATERIALIZED VIEW public.mv_user_ltv IS 'Lifetime value per user; refreshed nightly by pg_cron.';
