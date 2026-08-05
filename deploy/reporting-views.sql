-- Reporting views for governed execution.
-- CP-6/M2 origin (the CP-7 `sql_backing: views` pattern arriving early);
-- extended at CP-7 task 7.0 with the seed-packet delta (D-81).
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
-- are owned by the role that runs this file — `postgres`, which sees
-- through RLS on the base tables. On the pilot that is true twice over:
-- Supabase's `postgres` holds BYPASSRLS (measured; `rolsuper = false` —
-- the D-71/F3 fact) AND owns the base tables (owner exemption, absent
-- FORCE ROW LEVEL SECURITY). Either suffices; the verify section checks
-- both. **These views are therefore a deliberate, narrow, audited hole
-- in RLS.** That is the entire mechanism, and it is why the rule below
-- is absolute:
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
GRANT USAGE ON SCHEMA reporting TO example_exec;
-- The execution role reads views here and nothing else: no CREATE, so it
-- cannot add a view of its own that widens the hole.
REVOKE CREATE ON SCHEMA reporting FROM example_exec, PUBLIC;

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

-- ─────────────────────────────────────────────────────────────────────
-- CP-7 TASK 7.0 — seed-packet delta (2026-07-24, D-81)
--
-- The twelve views above went live at CP-6/M2 and already flow through
-- the product path (KB sync PR #20, enrichment PR #21, lineage graph).
-- They were drafted before the benchmark seed packet
-- (`benchmark/suite/benchmark-seed-v0.yaml`) pinned what the recurring
-- reports actually query; five of its Supabase-backed cases cannot be
-- served by them. The five views below close exactly that gap — scoped
-- to the seed packet and no broader. (The plan's other scoping input,
-- certified metrics, contributes nothing yet: the KB has no metrics/
-- catalog — the benchmark's recorded KB defect.)
--
-- Already served without new surface, for the record: RB-02
-- (plan × status subscriber counts) and RB-10 (churn-risk scorecard)
-- both resolve through v_subscriptions_by_plan.
--
-- Two deliberate differences from the twelve:
--   * Buckets pin UTC explicitly ((col AT TIME ZONE 'UTC')::date),
--     matching the seed goldens' semantics in the SQL itself rather
--     than inheriting the server TimeZone (Supabase defaults to UTC,
--     so live numbers agree; the contract is now visible in the text).
--   * Options are explicit: WITH (security_invoker = false) states the
--     mechanism this file exists for instead of inheriting a default,
--     and security_barrier = true keeps the planner from pushing
--     non-leakproof predicates below the aggregation. The twelve above
--     predate the D-81 ruling and are left untouched.
-- ─────────────────────────────────────────────────────────────────────

-- --- signups by day (RB-01 — the smoke-journey case; RB-05 stage 4) ---
-- Zero-signup days are absent (GROUP BY), per the RB-01 resolution:
-- fill client-side for a continuous axis. A day's count can be 1 on
-- this ~24-user estate; the row carries a date and a count, nothing
-- else — same accepted class as v_daily_activity.
CREATE OR REPLACE VIEW reporting.v_user_signups_by_day
    WITH (security_invoker = false, security_barrier = true) AS
SELECT (created_at AT TIME ZONE 'UTC')::date AS signup_day,
       count(*)                              AS new_users
  FROM public.users
 GROUP BY 1;

-- --- job journey transitions (RB-06) ----------------------------------
-- Transition-matrix source: one row per (day, from, to). from_status
-- IS NULL marks a job's first status entry — render as '(initial)'
-- downstream; the view keeps the raw NULL. changed_by_user_id is
-- deliberately not exposed (the aggregate journey, not the actor).
CREATE OR REPLACE VIEW reporting.v_job_status_transitions
    WITH (security_invoker = false, security_barrier = true) AS
SELECT (changed_at AT TIME ZONE 'UTC')::date AS changed_day,
       from_status,
       to_status,
       count(*)                              AS transitions
  FROM public.job_status_history
 GROUP BY 1, 2, 3;

-- --- new subscriptions by month (RB-08 supabase leg) ------------------
-- New rows by created_at month × status, to sit beside GA4's purchase
-- count in the reconciliation case. Counts, not revenue: subscriptions
-- carries no amount column (entities/conversion.md).
CREATE OR REPLACE VIEW reporting.v_subscriptions_new_by_month
    WITH (security_invoker = false, security_barrier = true) AS
SELECT date_trunc('month', created_at AT TIME ZONE 'UTC')::date AS month,
       status,
       count(*)                              AS new_subscriptions
  FROM public.subscriptions
 GROUP BY 1, 2;

-- --- AI runs by day and status (RB-09) --------------------------------
-- status stays a dimension on purpose: ai_runs.status is free text with
-- no CHECK constraint (its vocabulary is ungrounded — the KB defect
-- RB-09 flags), so the report grounds the actual failure spelling
-- through this view (SELECT status, sum(run_count) … GROUP BY 1) and
-- derives failure_pct itself. Baking status = 'failed' into the view
-- would hardcode exactly the value the KB cannot confirm.
CREATE OR REPLACE VIEW reporting.v_ai_runs_by_day
    WITH (security_invoker = false, security_barrier = true) AS
SELECT (started_at AT TIME ZONE 'UTC')::date AS run_day,
       status,
       count(*)                              AS run_count
  FROM public.ai_runs
 GROUP BY 1, 2;

-- --- activation funnel by signup cohort (RB-07) ------------------------
-- Same-month activation, deterministic per closed month: cohort = users
-- by UTC signup month; a cohort user counts toward a stage iff at least
-- one qualifying row exists before the cohort month's exclusive end.
-- count(*) FILTER (WHERE EXISTS …) ≡ the golden's count(DISTINCT
-- user_id) over a cohort join. Stage predicates mirror RB-07 exactly:
-- master/tailored CVs exclude soft-deleted rows, exports must be
-- status = 'completed', subscriptions count on any row. This is the one
-- view that must row-join inside — which is precisely why it is a view:
-- the execution role can never perform this join itself.
CREATE OR REPLACE VIEW reporting.v_activation_funnel_monthly
    WITH (security_invoker = false, security_barrier = true) AS
SELECT u.cohort_month,
       count(*) AS signed_up,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM public.master_cvs m
            WHERE m.user_id = u.id
              AND m.is_deleted = false
              AND (m.created_at AT TIME ZONE 'UTC') < u.next_month)) AS created_master_cv,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM public.tailored_cvs t
            WHERE t.user_id = u.id
              AND t.is_deleted = false
              AND (t.created_at AT TIME ZONE 'UTC') < u.next_month)) AS created_tailored_cv,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM public.exports e
            WHERE e.user_id = u.id
              AND e.status = 'completed'
              AND (e.created_at AT TIME ZONE 'UTC') < u.next_month)) AS exported,
       count(*) FILTER (WHERE EXISTS (
           SELECT 1 FROM public.subscriptions s
            WHERE s.user_id = u.id
              AND (s.created_at AT TIME ZONE 'UTC') < u.next_month)) AS subscribed
  FROM (SELECT id,
               date_trunc('month', created_at AT TIME ZONE 'UTC')::date AS cohort_month,
               date_trunc('month', created_at AT TIME ZONE 'UTC') + interval '1 month' AS next_month
          FROM public.users) u
 GROUP BY u.cohort_month;

-- Read-only, views only. New views added later are NOT granted
-- automatically: adding a view is a deliberate act, and so is exposing it.
-- (This grant runs after every view above, so re-running this whole file
-- is what grants a newly added view — deliberately.)
GRANT SELECT ON ALL TABLES IN SCHEMA reporting TO example_exec;

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
--      AND (column_name ~* '(^|_)(user_id|auth_user_id|email|full_name|name|title|company|notes|description|url|path|filename|checksum|token|customer_id|subscription_id)($|_)'
--           OR column_name ~* 'payload|content|text');
--
-- (The pattern is one long line on purpose: the original split it across
-- comment lines, which embedded newlines in the regex and silently
-- disarmed every branch after `full_name`. Fixed at task 7.0.)
--
-- And confirm the execution role can read the views but still not the
-- base tables:
--
--   SET ROLE example_exec;
--   SELECT count(*) FROM reporting.v_jobs_by_status;        -- rows expected
--   SELECT count(*) FROM reporting.v_user_signups_by_day;   -- rows expected (7.0)
--   SELECT count(*) FROM public.jobs;                 -- 0 (RLS still on)
--   RESET ROLE;
--
-- And that the RLS exemption these views ride on actually holds. The
-- owner's attributes (on the pilot: rolbypassrls = true):
--
--   SELECT rolname, rolbypassrls, rolsuper FROM pg_roles
--    WHERE rolname = (SELECT viewowner FROM pg_views
--                      WHERE schemaname = 'reporting' LIMIT 1);
--
-- If the owner ever rides on table ownership alone (rolbypassrls =
-- false), FORCE ROW LEVEL SECURITY on a base table would silently empty
-- every view over it (fails closed, but the report demo dies with it).
-- Expect zero rows:
--
--   SELECT c.relname
--     FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
--    WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity;
-- ─────────────────────────────────────────────────────────────────────
--
-- ROLLBACK:
--   DROP SCHEMA reporting CASCADE;
-- Task 7.0 delta only (leaves the CP-6 twelve in place):
--   DROP VIEW reporting.v_user_signups_by_day, reporting.v_job_status_transitions,
--             reporting.v_subscriptions_new_by_month, reporting.v_ai_runs_by_day,
--             reporting.v_activation_funnel_monthly;
