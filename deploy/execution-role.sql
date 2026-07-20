-- Execution role provisioning (CP-6/M2, ruling G3).
--
-- Governed execution runs directly against the customer's OLTP database
-- — the deployment-configurable exception the product spec allows for
-- DW-less estates, and the plan's pilot-ending risk class. The guardrails
-- that make it acceptable are layered, and this file is the bottom layer:
-- a role that *cannot* write, enforced by the database rather than by any
-- code of ours.
--
-- The layers above it (statement_timeout per query, row caps enforced
-- during streaming, a SELECT-only parser at both the gateway and the
-- executor) are all filters, and filters have bugs. This one is a wall.
-- The executor verifies these grants at startup AND before every query,
-- and refuses to serve execution if the role can write.
--
-- Run as a superuser (Supabase: the SQL editor as `postgres`) against
-- the customer database. Review every line before running it: this is
-- the file that decides what an agent can reach.
--
-- ─────────────────────────────────────────────────────────────────────
-- BEFORE YOU RUN
--   1. Replace <PASSWORD> with a generated secret. Do not reuse the
--      introspection role's password — these are two distinct identities
--      on purpose (G3), so that a leak of one is not a leak of both.
--   2. Set SCHEMAS below to exactly the schemas execution may read.
--      Anything omitted is unreachable, which is the desired default.
--   3. Store the resulting DSN as a vault reference, never in a config
--      file. The runner resolves it at job time (J-4).
-- ─────────────────────────────────────────────────────────────────────

BEGIN;

-- 1. The role. LOGIN only: no CREATEDB, no CREATEROLE, no SUPERUSER, no
--    BYPASSRLS. The executor's startup check refuses any of these.
CREATE ROLE contextlayer_exec LOGIN PASSWORD '<PASSWORD>'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;

-- 2. Connect, but nothing implied by it. GRANT needs a literal database
--    identifier, so the name is interpolated rather than called inline
--    (`GRANT ... ON DATABASE current_database()` is a syntax error).
--    This form works whatever the database is called — on Supabase it is
--    `postgres`.
DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT ON DATABASE %I TO contextlayer_exec', current_database());
END
$$;

-- 3. Read access, schema by schema. Repeat this block per schema you
--    intend to expose; do not loop over every schema in the database.
--    (Edit the schema name; the statements are deliberately explicit so
--    that reviewing this file tells you exactly what is reachable.)

-- --- schema: public ---------------------------------------------------
GRANT USAGE ON SCHEMA public TO contextlayer_exec;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO contextlayer_exec;
-- Tables created *later* by the role running this script are readable
-- too, so a migration does not silently make the agent blind. Still
-- SELECT-only.
--
-- Caveat worth knowing: default privileges are recorded per creating
-- role, not per schema. This covers objects created by the role you are
-- running as (on Supabase, `postgres` — which is what the dashboard and
-- most migrations use). If some other role creates tables here, add a
-- matching line for it:
--   ALTER DEFAULT PRIVILEGES FOR ROLE <creator> IN SCHEMA public
--       GRANT SELECT ON TABLES TO contextlayer_exec;
-- Otherwise new tables from that creator simply will not be readable —
-- which fails closed (the agent sees less), not open.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO contextlayer_exec;
-- CREATE on a schema would let the role make objects it could then write.
REVOKE CREATE ON SCHEMA public FROM contextlayer_exec;

-- --- add further schemas here, same four statements ------------------
--
-- On Supabase, do NOT add `auth` or `vault`: `auth.users` holds email
-- addresses, password hashes, and refresh tokens, and `vault` holds
-- decrypted secrets. Neither is reporting context, and both would be
-- readable by any agent query the moment they are granted. `storage`
-- likewise exposes object metadata for every uploaded file. Grant the
-- schemas that hold business data and nothing else.

-- 4. Belt and braces: PUBLIC's default CREATE on `public` predates this
--    role and would otherwise apply to it. (No-op on PG15+, where this
--    is already the default.)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- 5. Make read-only the role's default posture even for a session that
--    somehow escapes the executor's own transaction settings.
--
--    Note what this is and is not: the role can `SET
--    default_transaction_read_only = off` on its own session, so this is
--    a convenience backstop, NOT the wall. The wall is the absence of
--    write GRANTs in step 3 — with this flag switched off, writes still
--    fail with InsufficientPrivilege. If you are ever tempted to rely on
--    this line instead of the grants, don't.
ALTER ROLE contextlayer_exec SET default_transaction_read_only = on;
-- A per-query timeout is set by the executor from the profile guardrail;
-- this is the backstop for any connection it does not set.
ALTER ROLE contextlayer_exec SET statement_timeout = '60s';
-- Long-idle transactions on an OLTP primary hold locks and bloat; cap them.
ALTER ROLE contextlayer_exec SET idle_in_transaction_session_timeout = '60s';

COMMIT;

-- ─────────────────────────────────────────────────────────────────────
-- VERIFY (expected: zero rows from each of the first two queries)
--
-- Any write grant reachable through role membership:
--   SELECT table_schema, table_name, privilege_type
--     FROM information_schema.role_table_grants
--    WHERE grantee IN (SELECT rolname FROM pg_roles
--                       WHERE pg_has_role('contextlayer_exec', oid, 'USAGE'))
--      AND privilege_type IN
--          ('INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER');
--
-- Any schema the role could create objects in:
--   SELECT nspname FROM pg_namespace
--    WHERE has_schema_privilege('contextlayer_exec', nspname, 'CREATE')
--      AND nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema';
--
-- Role attributes (all four booleans must be false):
--   SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
--     FROM pg_roles WHERE rolname = 'contextlayer_exec';
--
-- The executor runs these same checks itself and refuses to serve
-- execution if any of them comes back non-empty, so a mistake here fails
-- closed at startup rather than opening a write path.
-- ─────────────────────────────────────────────────────────────────────
--
-- ROLLBACK / decommission:
--   REASSIGN OWNED BY contextlayer_exec TO postgres;  -- should own nothing
--   DROP OWNED BY contextlayer_exec;
--   DROP ROLE contextlayer_exec;
