-- Reporting views for governed execution (CP-6/M2; the CP-7 `sql_backing:
-- views` pattern arriving early).
--
-- ─────────────────────────────────────────────────────────────────────
-- WHY THIS FILE EXISTS
--
-- Every table in `public` has Row Level Security with per-user policies
-- (`is_current_user(user_id)`, `auth.uid() = auth_user_id`). The
-- execution role has no logged-in user, so `auth.uid()` is NULL and it
-- reads **zero rows from every table**. That is the security model
-- working correctly — and it also means governed execution cannot answer
-- a single business question against base tables.
--
-- The answer the platform plan already anticipates ("reporting-views for
-- anything recurring"; Looker Studio's adapter declares
-- `sql_backing: views`) is this: expose *aggregates* through views, never
-- base tables.
--
-- ─────────────────────────────────────────────────────────────────────
-- READ THIS BEFORE APPLYING — what these views actually do
--
-- A Postgres view evaluates RLS as its OWNER, not its caller. These views
-- are owned by `postgres`, which holds BYPASSRLS. **They are therefore a
-- deliberate, narrow, audited hole in RLS.** That is the entire mechanism,
-- and it is why the rule below is absolute:
--
--     EVERY COLUMN OF EVERY VIEW HERE MUST BE AN AGGREGATE OR A
--     NON-IDENTIFYING DIMENSION. No user_id. No email. No name. No
--     free text the user wrote. No id that joins back to a person.
--
-- A view added here that returns a row per user re-exposes exactly what
-- RLS was protecting, to an agent, silently. If you extend this file,
-- extend it with counts and sums grouped by status, type, or period —
-- and re-run the guard query at the bottom, which fails loudly on any
-- column that looks identifying.
--
-- Small-group note: counts grouped finely enough can identify individuals
-- (a status with exactly one user). The example estate is a small fixture user population, so
-- treat any count of 1-2 as potentially personal. `v_daily_activity`
-- deliberately reports no per-user dimension for this reason.
--
-- Run as `postgres` in the Supabase SQL editor.
-- ─────────────────────────────────────────────────────────────────────

BEGIN;

CREATE SCHEMA IF NOT EXISTS reporting;
GRANT USAGE ON SCHEMA reporting TO contextlayer_exec;
-- The execution role reads views here and nothing else: no CREATE, so it
-- cannot add a view of its own that widens the hole.
REVOKE CREATE ON SCHEMA reporting FROM contextlayer_exec, PUBLIC;

-- --- job pipeline ----------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_jobs_by_status AS
SELECT status,
       count(*)                              AS job_count,
       count(DISTINCT user_id)               AS distinct_users,
       min(created_at)::date                 AS first_created,
       max(created_at)::date                 AS last_created
  FROM public.jobs
 GROUP BY status;

CREATE OR REPLACE VIEW reporting.v_jobs_by_month AS
SELECT date_trunc('month', created_at)::date AS month,
       count(*)                              AS job_count,
       count(DISTINCT user_id)               AS distinct_users,
       count(*) FILTER (WHERE applied_at IS NOT NULL) AS applied_count
  FROM public.jobs
 GROUP BY 1;

-- --- CV production ---------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_cv_production AS
SELECT date_trunc('month', created_at)::date AS month,
       language,
       count(*)                              AS tailored_cv_count,
       count(DISTINCT user_id)               AS distinct_users,
       count(*) FILTER (WHERE is_deleted)    AS deleted_count
  FROM public.tailored_cvs
 GROUP BY 1, 2;

CREATE OR REPLACE VIEW reporting.v_master_cvs_by_language AS
SELECT language,
       source_type,
       count(*)                              AS master_cv_count,
       count(DISTINCT user_id)               AS distinct_users
  FROM public.master_cvs
 WHERE NOT is_deleted
 GROUP BY 1, 2;

-- --- AI usage and cost ----------------------------------------------
CREATE OR REPLACE VIEW reporting.v_ai_runs_by_flow AS
SELECT flow_type,
       provider,
       model_name,
       status,
       count(*)                              AS run_count,
       count(DISTINCT user_id)               AS distinct_users,
       sum(input_tokens)                     AS input_tokens,
       sum(output_tokens)                    AS output_tokens,
       sum(total_tokens)                     AS total_tokens,
       round(avg(EXTRACT(EPOCH FROM (completed_at - started_at)))::numeric, 2)
                                             AS avg_seconds
  FROM public.ai_runs
 GROUP BY 1, 2, 3, 4;

CREATE OR REPLACE VIEW reporting.v_ai_tokens_by_month AS
SELECT date_trunc('month', started_at)::date AS month,
       provider,
       sum(total_tokens)                     AS total_tokens,
       count(*)                              AS run_count,
       count(*) FILTER (WHERE status <> 'completed') AS non_completed_count
  FROM public.ai_runs
 GROUP BY 1, 2;

-- --- exports / imports ----------------------------------------------
CREATE OR REPLACE VIEW reporting.v_exports_by_format AS
SELECT format,
       status,
       count(*)                              AS export_count,
       count(DISTINCT user_id)               AS distinct_users
  FROM public.exports
 GROUP BY 1, 2;

CREATE OR REPLACE VIEW reporting.v_imports_by_parser AS
SELECT parser_name,
       status,
       count(*)                              AS import_count,
       count(DISTINCT user_id)               AS distinct_users
  FROM public.imports
 GROUP BY 1, 2;

-- --- storage ---------------------------------------------------------
CREATE OR REPLACE VIEW reporting.v_files_by_type AS
SELECT file_type,
       mime_type,
       count(*)                              AS file_count,
       count(DISTINCT user_id)               AS distinct_users,
       sum(size_bytes)                       AS total_bytes,
       round(avg(size_bytes))                AS avg_bytes
  FROM public.files
 WHERE NOT is_deleted
 GROUP BY 1, 2;

-- --- subscriptions (plan mix only; no provider customer ids) ---------
CREATE OR REPLACE VIEW reporting.v_subscriptions_by_plan AS
SELECT plan_code,
       status,
       count(*)                              AS subscription_count,
       count(*) FILTER (WHERE cancel_at_period_end) AS cancelling_count
  FROM public.subscriptions
 GROUP BY 1, 2;

-- --- cross-entity activity (no user dimension, deliberately) ---------
CREATE OR REPLACE VIEW reporting.v_daily_activity AS
SELECT d::date AS day,
       (SELECT count(*) FROM public.jobs          j WHERE j.created_at::date = d::date) AS jobs_created,
       (SELECT count(*) FROM public.tailored_cvs  t WHERE t.created_at::date = d::date) AS cvs_tailored,
       (SELECT count(*) FROM public.exports       e WHERE e.created_at::date = d::date) AS exports_created,
       (SELECT count(*) FROM public.ai_runs       a WHERE a.started_at::date = d::date) AS ai_runs_started
  FROM generate_series(
         (SELECT min(created_at)::date FROM public.jobs),
         CURRENT_DATE, interval '1 day') AS d;

-- --- cohort sizes (counts only; nothing that names a person) ---------
CREATE OR REPLACE VIEW reporting.v_user_cohorts AS
SELECT date_trunc('month', created_at)::date AS signup_month,
       locale,
       default_cv_language,
       count(*)                              AS user_count,
       count(*) FILTER (WHERE onboarding_completed) AS onboarded_count
  FROM public.users
 GROUP BY 1, 2, 3;

-- Read-only, views only. New views added later are NOT granted
-- automatically: adding a view is a deliberate act, and so is exposing it.
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO contextlayer_exec;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────
-- GUARD — run this after applying. It must return ZERO rows.
--
-- It fails on any column in `reporting` whose name suggests it identifies
-- a person. It is a lint, not a proof: a column called `top_value` that
-- happens to contain an email would pass. The rule above ("aggregates and
-- non-identifying dimensions only") is the actual contract; this catches
-- the obvious slips.
--
--   SELECT table_name, column_name
--     FROM information_schema.columns
--    WHERE table_schema = 'reporting'
--      AND (column_name ~* '(^|_)(user_id|auth_user_id|email|full_name|
--                              name|title|company|notes|description|
--                              url|path|filename|checksum|token|
--                              customer_id|subscription_id)($|_)'
--           OR column_name ~* 'payload|content|text');
--
-- And confirm the execution role can read the views but still not the
-- base tables:
--
--   SET ROLE contextlayer_exec;
--   SELECT count(*) FROM reporting.v_jobs_by_status;  -- rows expected
--   SELECT count(*) FROM public.jobs;                 -- 0 (RLS still on)
--   RESET ROLE;
-- ─────────────────────────────────────────────────────────────────────
--
-- ROLLBACK:
--   DROP SCHEMA reporting CASCADE;
