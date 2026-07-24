"""Guardrailed executors (benchmark.executors, R3)."""

import pytest

from benchmark.executors import (
    ROW_CAP,
    STATEMENT_TIMEOUT_MS,
    ExecResult,
    ScriptedExecutor,
    SqlGuardError,
    assert_select_only,
)


@pytest.mark.parametrize("stmt", [
    "SELECT 1",
    "SELECT count(*) FROM public.users WHERE created_at >= '2026-06-01'",
    "SET statement_timeout='30s'; SELECT plan_code, count(*) FROM public.subscriptions GROUP BY 1",
    "WITH c AS (SELECT id FROM public.users) SELECT count(*) FROM c",
])
def test_guard_allows_select_and_set_timeout(stmt):
    assert_select_only(stmt)  # does not raise


@pytest.mark.parametrize("stmt", [
    "DELETE FROM public.users",
    "UPDATE public.users SET email = 'x'",
    "INSERT INTO public.users (id) VALUES (1)",
    "DROP TABLE public.users",
    "TRUNCATE public.users",
    "WITH d AS (DELETE FROM public.users RETURNING id) SELECT * FROM d",  # CTE-embedded DML
    "SET role = 'admin'; SELECT 1",  # non-timeout SET
    "SELECT 1; SELECT 2",  # two queries in one call
])
def test_guard_rejects_non_select(stmt):
    with pytest.raises(SqlGuardError):
        assert_select_only(stmt)


def test_guard_rejects_unparseable():
    with pytest.raises(SqlGuardError):
        assert_select_only("SELECT FROM WHERE (")


def test_scripted_executor_records_and_guards():
    ex = ScriptedExecutor({"supabase:sql": ExecResult(ok=True, columns=["n"], rows=[[7]], row_count=1)})
    res = ex.run_sql("supabase", "SELECT count(*) FROM public.users")
    assert res.ok and res.rows == [[7]]
    assert ex.calls[0]["kind"] == "sql"
    with pytest.raises(SqlGuardError):
        ex.run_sql("supabase", "DELETE FROM public.users")


def test_constants():
    assert ROW_CAP == 10_000 and STATEMENT_TIMEOUT_MS == 30_000
