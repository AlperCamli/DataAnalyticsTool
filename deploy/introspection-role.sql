-- Introspection role provisioning (D-71.2, security review #2 F3).
--
-- The companion to `deploy/execution-role.sql`, for the *other*
-- connection into the customer database: the one the snapshot connector
-- opens to read the catalog. On the pilot that connection authenticated
-- as `postgres` — none of whose privileges introspection has ever needed.
--
-- Measured on the example estate rather than assumed, because the detail
-- matters: Supabase's `postgres` reports `rolsuper = false`. It is not a
-- superuser. It holds CREATEDB, CREATEROLE and **BYPASSRLS**. A check
-- written to look only for SUPERUSER — the obvious way to write it —
-- would have passed this connection cleanly. The startup check tests
-- both attributes for exactly that reason.
--
-- What made that worth fixing before CP-7 rather than after: BYPASSRLS.
-- Nothing today reads customer *rows* over the introspection connection
-- (the connector reads pg_catalog and nothing else, and usage mining
-- stays source-side per UP-1), so the exposure was latent. But the first
-- capability that does read rows over this connection — sampling, usage
-- statistics, a profiling pass — would silently see through every row
-- level security policy on the estate, and would do so without a single
-- line of code looking wrong. This role removes that future.
--
-- Run as a superuser (Supabase: the SQL editor as `postgres`) against
-- the customer database. Review every line before running it.
--
-- ─────────────────────────────────────────────────────────────────────
-- BEFORE YOU RUN
--   1. Replace <PASSWORD> with a generated secret. Do not reuse the
--      execution role's password — two identities, two secrets, so that
--      a leak of one is not a leak of both (G3, and the same logic here).
--   2. Set the schema list in step 3 to the schemas you introspect.
--   3. Store the resulting DSN as a vault reference, never in a config
--      file. The runner resolves it at job time (J-4).
-- ─────────────────────────────────────────────────────────────────────

BEGIN;

-- 1. The role. LOGIN only: none of the four attributes the startup check
--    refuses, BYPASSRLS explicitly among them.
CREATE ROLE contextlayer_introspect LOGIN PASSWORD '<PASSWORD>'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

-- 2. Connect, and nothing implied by it. (As in the execution file, GRANT
--    needs a literal database identifier, so the name is interpolated.)
DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO contextlayer_introspect', current_database());
END
$$;

-- 3. USAGE on the schemas you introspect — and deliberately NO `GRANT
--    SELECT` on anything.
--
--    Why that is enough, stated plainly because it looks wrong at first:
--    the connector reads `pg_catalog` only (see connectors/postgres/
--    catalog.py, whose module docstring commits to it). The pg_catalog
--    tables are SELECT-able by PUBLIC and are *not* privilege-filtered,
--    so this role can read the full shape of the estate — table names,
--    columns, types, constraints, view definitions — while holding no
--    privilege to read a single row of data out of any of them.
--
--    That asymmetry is the entire design: shape without contents. It is
--    also why swapping the pilot from `postgres` to this role produces a
--    byte-identical snapshot — the catalog answers the same regardless
--    of who is asking.
--
--    (If a future capability reads row data over this connection, it
--    will fail loudly here rather than quietly succeed with BYPASSRLS.
--    That is the intended outcome, not an oversight to work around: it
--    forces a deliberate grant, reviewed on its own merits.)
GRANT USAGE ON SCHEMA public TO contextlayer_introspect;
-- --- add further introspected schemas here, one line each -------------

-- 4. No object creation, from the role or inherited from PUBLIC.
REVOKE CREATE ON SCHEMA public FROM contextlayer_introspect;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 5. Session posture. Introspection is read-only and short; a catalog
--    read that runs for a minute is a symptom, not a workload.
ALTER ROLE contextlayer_introspect SET default_transaction_read_only = on;
ALTER ROLE contextlayer_introspect SET statement_timeout = '60s';
ALTER ROLE contextlayer_introspect SET idle_in_transaction_session_timeout = '60s';

COMMIT;

-- ─────────────────────────────────────────────────────────────────────
-- VERIFY (expected: zero rows from each of the first two queries)
--
-- Any table privilege at all, reachable through role membership. Note
-- this is stricter than the execution role's check: introspection has no
-- business holding SELECT either.
--   SELECT table_schema, table_name, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE grantee IN (SELECT rolname FROM pg_roles
--                       WHERE pg_has_role('contextlayer_introspect', oid, 'USAGE'))
--      AND table_schema NOT IN ('pg_catalog', 'information_schema');
--
-- Any schema the role could create objects in:
--   SELECT nspname FROM pg_namespace
--    WHERE has_schema_privilege('contextlayer_introspect', nspname, 'CREATE')
--      AND nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema';
--
-- Role attributes (all four booleans must be false):
--   SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
--     FROM pg_roles WHERE rolname = 'contextlayer_introspect';
--
-- The connector runs the attribute check itself at the start of every
-- live snapshot job and refuses to introspect if SUPERUSER or BYPASSRLS
-- comes back true, so a mistake here fails closed at job start rather
-- than producing a snapshot nobody knows was over-privileged.
-- ─────────────────────────────────────────────────────────────────────
--
-- ROLLBACK / decommission:
--   REASSIGN OWNED BY contextlayer_introspect TO postgres;  -- owns nothing
--   DROP OWNED BY contextlayer_introspect;
--   DROP ROLE contextlayer_introspect;
