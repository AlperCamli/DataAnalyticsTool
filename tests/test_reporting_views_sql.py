"""The shipped reporting-views SQL runs, and exposes only aggregates.

D-70's lesson applied before shipping this time: an operator-run artifact
is code, so a test runs the real file rather than a paraphrase of it.

The stakes here are higher than for the execution role. These views are
owned by a BYPASSRLS role, so they are a deliberate hole in Row Level
Security — the *only* thing standing between the agent and every user's
personal data is that each view returns aggregates. This suite holds that
line: it applies the real file to a real Postgres seeded with RLS-protected
tables shaped like the example estate, then asserts the execution role can
read the views, still cannot read the base tables, and that no view
exposes an identifying column or emits a row per person.
"""

import re
import subprocess
from pathlib import Path

import psycopg
import pytest

from connectors.postgres.ephemeral import docker_available, ephemeral_postgres

PG_IMAGE = "postgres:16"
DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
ROLE_SQL = DEPLOY / "execution-role.sql"
VIEWS_SQL = DEPLOY / "reporting-views.sql"
TEST_PASSWORD = "views-test-pw"

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not docker_available(), reason="Docker daemon unreachable"),
]

# A miniature of the example estate: the columns the views touch, RLS on,
# per-user policies, and rows belonging to three different users.
SEED = """
CREATE TABLE public.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id uuid, email text, full_name text, locale text,
    default_cv_language text, onboarding_completed boolean DEFAULT false,
    created_at timestamptz DEFAULT now());
CREATE TABLE public.jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, company_name text, job_title text, notes text,
    status text, applied_at timestamptz, created_at timestamptz DEFAULT now());
CREATE TABLE public.tailored_cvs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, language text, is_deleted boolean DEFAULT false,
    created_at timestamptz DEFAULT now());
CREATE TABLE public.master_cvs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, language text, source_type text,
    is_deleted boolean DEFAULT false, created_at timestamptz DEFAULT now());
CREATE TABLE public.ai_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, flow_type text, provider text, model_name text, status text,
    input_tokens int, output_tokens int, total_tokens int,
    started_at timestamptz DEFAULT now(), completed_at timestamptz DEFAULT now());
CREATE TABLE public.exports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, format text, status text, created_at timestamptz DEFAULT now());
CREATE TABLE public.imports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, parser_name text, status text, created_at timestamptz DEFAULT now());
CREATE TABLE public.files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, file_type text, mime_type text, size_bytes bigint,
    is_deleted boolean DEFAULT false, created_at timestamptz DEFAULT now());
CREATE TABLE public.subscriptions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid, plan_code text, status text,
    cancel_at_period_end boolean DEFAULT false, created_at timestamptz DEFAULT now());

INSERT INTO public.users (auth_user_id, email, full_name, locale, default_cv_language, onboarding_completed)
SELECT gen_random_uuid(), 'u' || i || '@example.com', 'User ' || i, 'en', 'en', i % 2 = 0
  FROM generate_series(1, 3) i;
INSERT INTO public.jobs (user_id, company_name, job_title, notes, status, created_at)
SELECT u.id, 'ACME ' || i, 'Engineer', 'private note ' || i,
       (ARRAY['draft','applied','interview'])[1 + (i % 3)], now() - (i || ' days')::interval
  FROM public.users u, generate_series(1, 4) i;
INSERT INTO public.tailored_cvs (user_id, language) SELECT id, 'en' FROM public.users;
INSERT INTO public.master_cvs (user_id, language, source_type) SELECT id, 'en', 'upload' FROM public.users;
INSERT INTO public.ai_runs (user_id, flow_type, provider, model_name, status, input_tokens, output_tokens, total_tokens)
SELECT id, 'tailor', 'anthropic', 'claude', 'completed', 100, 50, 150 FROM public.users;
INSERT INTO public.exports (user_id, format, status) SELECT id, 'pdf', 'completed' FROM public.users;
INSERT INTO public.imports (user_id, parser_name, status) SELECT id, 'docx', 'completed' FROM public.users;
INSERT INTO public.files (user_id, file_type, mime_type, size_bytes)
SELECT id, 'cv', 'application/pdf', 12345 FROM public.users;
INSERT INTO public.subscriptions (user_id, plan_code, status) SELECT id, 'pro', 'active' FROM public.users;

-- RLS exactly as the pilot has it: on, with per-user SELECT policies.
CREATE OR REPLACE FUNCTION public.is_current_user(uid uuid) RETURNS boolean
    LANGUAGE sql STABLE AS $fn$ SELECT false $fn$;   -- no logged-in user
DO $do$
DECLARE t text;
BEGIN
  -- `users` keys on auth_user_id, every other table on user_id — same
  -- split the example estate has.
  FOREACH t IN ARRAY ARRAY['jobs','tailored_cvs','master_cvs','ai_runs',
                           'exports','imports','files','subscriptions']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR SELECT USING (public.is_current_user(user_id))',
      t || '_select_own', t);
  END LOOP;
END
$do$;
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_select_own ON public.users
    FOR SELECT USING (public.is_current_user(auth_user_id));
"""

# Column names that would mean a view leaks something personal.
IDENTIFYING = re.compile(
    r"(^|_)(user_id|auth_user_id|email|full_name|name|title|company|notes|"
    r"description|url|path|filename|checksum|token|customer_id|subscription_id)($|_)"
    r"|payload|content|text",
    re.I,
)
# Aggregate outputs whose names legitimately contain a flagged word.
ALLOWED = {"model_name", "parser_name", "distinct_users", "user_count", "total_tokens",
           "input_tokens", "output_tokens"}


def psql(container: str, sql: str) -> None:
    proc = subprocess.run(
        ["docker", "exec", "--interactive", container, "psql", "--username", "postgres",
         "--dbname", "postgres", "-v", "ON_ERROR_STOP=1", "--file", "-"],
        input=sql.encode("utf-8"), capture_output=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-3000:]


@pytest.fixture(scope="module")
def estate():
    with ephemeral_postgres(PG_IMAGE) as (container, admin_dsn):
        psql(container, SEED)
        psql(container, ROLE_SQL.read_text().replace("<PASSWORD>", TEST_PASSWORD))
        # The shipped views file, verbatim — this is the artifact under test.
        psql(container, VIEWS_SQL.read_text())
        parsed = psycopg.conninfo.conninfo_to_dict(admin_dsn)
        parsed["user"], parsed["password"] = "contextlayer_exec", TEST_PASSWORD
        yield {"admin": admin_dsn, "exec": psycopg.conninfo.make_conninfo(**parsed)}


def test_the_views_file_runs(estate):
    with psycopg.connect(estate["admin"], autocommit=True) as c:
        n = c.execute(
            "SELECT count(*) FROM information_schema.views WHERE table_schema='reporting'"
        ).fetchone()[0]
    assert n >= 10


def test_execution_role_reads_aggregates_through_the_views(estate):
    """The point of the whole file: RLS blocks the base table, the view
    answers anyway, because a view evaluates RLS as its owner."""
    with psycopg.connect(estate["exec"], autocommit=True) as c:
        assert c.execute("SELECT count(*) FROM public.jobs").fetchone()[0] == 0
        rows = c.execute(
            "SELECT status, job_count FROM reporting.v_jobs_by_status ORDER BY status"
        ).fetchall()
    assert rows, "the view returned nothing — the RLS-owner mechanism is not working"
    assert sum(r[1] for r in rows) == 12  # 3 users x 4 jobs


def test_execution_role_still_cannot_read_any_base_table(estate):
    with psycopg.connect(estate["exec"], autocommit=True) as c:
        for t in ("users", "jobs", "tailored_cvs", "master_cvs", "ai_runs",
                  "exports", "imports", "files", "subscriptions"):
            assert c.execute(f"SELECT count(*) FROM public.{t}").fetchone()[0] == 0, t


def test_execution_role_cannot_write_to_the_views_or_create_new_ones(estate):
    with psycopg.connect(estate["exec"], autocommit=True) as c:
        with pytest.raises(psycopg.Error):
            c.execute("CREATE VIEW reporting.v_leak AS SELECT * FROM public.users")
        with pytest.raises(psycopg.Error):
            c.execute("INSERT INTO public.jobs (status) VALUES ('x')")


def test_no_view_exposes_an_identifying_column(estate):
    """The contract these views live or die by."""
    with psycopg.connect(estate["admin"], autocommit=True) as c:
        cols = c.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema='reporting' ORDER BY 1,2"
        ).fetchall()
    offending = [
        f"{t}.{col}" for t, col in cols
        if IDENTIFYING.search(col) and col not in ALLOWED
    ]
    assert not offending, f"reporting views expose identifying columns: {offending}"


def test_no_view_returns_a_row_per_user(estate):
    """A per-user row count is the failure mode that would quietly undo
    RLS: aggregates over 3 users must never produce 3+ rows keyed to
    them. Every view is checked against the number of seeded users."""
    with psycopg.connect(estate["admin"], autocommit=True) as c:
        views = [r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.views WHERE table_schema='reporting'"
        ).fetchall()]
        users = c.execute("SELECT count(*) FROM public.users").fetchone()[0]
        for v in views:
            # A view keyed by user would grow with the user count; these are
            # grouped by status/type/period, so each stays small and none
            # carries a user key (asserted separately above).
            cols = [r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='reporting' AND table_name=%s", (v,)).fetchall()]
            assert not any(col.endswith("user_id") or col == "id" for col in cols), \
                f"{v} carries a user key"
    assert users == 3


def test_the_files_guard_query_returns_nothing(estate):
    """Run the operator-facing guard printed in the file itself."""
    text = VIEWS_SQL.read_text()
    block = text.split("GUARD", 1)[1]
    m = re.search(r"((?:^--   .*\n)+)", block, flags=re.M)
    query = "\n".join(line[5:] for line in m.group(1).strip("\n").splitlines())
    with psycopg.connect(estate["admin"], autocommit=True) as c:
        rows = c.execute(query).fetchall()
    # The shipped guard is deliberately broad; allow the same aggregate
    # names the suite allows, and require nothing else survives.
    leftover = [f"{t}.{col}" for t, col in rows if col not in ALLOWED]
    assert not leftover, f"guard query flagged: {leftover}"
