"""Live execution against the example estate (CP-6/M2 exit criteria).

Env-gated, following the task 1.3/1.4 pattern: these are the tests that
prove the executors work against the actual APIs and the actual customer
database, not against recorded shapes. They skip silently without the
gate so the default suite stays hermetic.

    # Supabase (needs the execution role from deploy/execution-role.sql)
    CTXLAYER_PG_EXEC_LIVE=1 CTXLAYER_PG_EXEC_DSN=postgres://... \\
      .venv/bin/python -m pytest tests/test_live_execute.py -v

    # GA4
    CTXLAYER_GA4_LIVE=1 CTXLAYER_GA4_PROPERTY_ID=... \\
      GOOGLE_APPLICATION_CREDENTIALS=... .venv/bin/python -m pytest ...

    # GSC
    CTXLAYER_GSC_LIVE=1 CTXLAYER_GSC_SITE_URL=... \\
      GOOGLE_APPLICATION_CREDENTIALS=... .venv/bin/python -m pytest ...
"""

import os

import pytest

from connectors.sdk import ExecuteRequest, Guardrails, GuardrailViolation, Identity

IDENTITY = Identity(
    subject="oidc|live-test",
    roles=("steward",),
    session_id="s-live",
    intent="M2 live execution evidence",
)


# --- Supabase / Postgres ----------------------------------------------------


@pytest.mark.postgres_live
@pytest.mark.skipif(
    not os.environ.get("CTXLAYER_PG_EXEC_LIVE"),
    reason="set CTXLAYER_PG_EXEC_LIVE=1 and CTXLAYER_PG_EXEC_DSN (execution role)",
)
class TestLivePostgresExecution:
    @staticmethod
    def config():
        return {
            "system": "supabase",
            "mode": "live",
            "execute_dsn": os.environ["CTXLAYER_PG_EXEC_DSN"],
        }

    def executor(self):
        from connectors.postgres.executor import PostgresExecutor

        return PostgresExecutor()

    def test_startup_role_check_passes(self):
        """G3 against the example estate: the configured execution role is
        read-only at the database level."""
        facts = self.executor().preflight(self.config())
        assert facts["role"]
        print(f"\n[live] execution role={facts['role']} engine={facts['engine_version']}")

    def test_select_returns_rows(self):
        result = self.executor().execute(
            self.config(),
            ExecuteRequest(dialect="sql", statement="SELECT current_database() AS db, 1 AS one"),
            Guardrails(row_cap=10, timeout_s=15),
            IDENTITY,
        )
        assert result.row_count == 1
        assert result.truncated is False
        print(f"\n[live] executed on {result.source}")

    def test_write_is_refused_at_the_database_role(self):
        """The staged-bypass path against the example estate: bypass the
        executor's parser and go straight at the driver, exactly as a
        compromised validator would. The role must still refuse."""
        import psycopg

        dsn = os.environ["CTXLAYER_PG_EXEC_DSN"]
        with psycopg.connect(dsn, autocommit=True) as conn:
            with pytest.raises(
                (psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction)
            ):
                conn.execute("CREATE TABLE contextlayer_canary_should_not_exist (id int)")

    def test_row_cap_truncates(self):
        result = self.executor().execute(
            self.config(),
            ExecuteRequest(
                dialect="sql",
                statement="SELECT i FROM generate_series(1, 1000) AS i",
            ),
            Guardrails(row_cap=10, timeout_s=15),
            IDENTITY,
        )
        assert len(result.rows) == 10
        assert result.truncated is True


# --- GA4 --------------------------------------------------------------------


@pytest.mark.ga4_live
@pytest.mark.skipif(
    not os.environ.get("CTXLAYER_GA4_LIVE"),
    reason="set CTXLAYER_GA4_LIVE=1, CTXLAYER_GA4_PROPERTY_ID, GOOGLE_APPLICATION_CREDENTIALS",
)
class TestLiveGA4Execution:
    @staticmethod
    def config():
        return {
            "system": "ga4",
            "mode": "api",
            "property_id": os.environ["CTXLAYER_GA4_PROPERTY_ID"],
            "credentials_file": os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        }

    def executor(self):
        from connectors.ga4.executor import GA4Executor

        return GA4Executor()

    def test_run_report_for_documented_fields(self):
        result = self.executor().execute(
            self.config(),
            ExecuteRequest(
                dialect="api",
                operation="runReport",
                body={
                    "dimensions": [{"name": "country"}],
                    "metrics": [{"name": "activeUsers"}],
                    "dateRanges": [{"startDate": "28daysAgo", "endDate": "yesterday"}],
                },
            ),
            Guardrails(row_cap=25, timeout_s=30),
            IDENTITY,
        )
        assert [c["name"] for c in result.columns] == ["country", "activeUsers"]
        print(f"\n[live] GA4 runReport: {result.row_count} rows, first={result.rows[:2]}")

    def test_undocumented_dimension_is_refused(self):
        """MT-8 against the live API: an undocumented dimension does not
        return data, it returns a refusal."""
        with pytest.raises(GuardrailViolation) as excinfo:
            self.executor().execute(
                self.config(),
                ExecuteRequest(
                    dialect="api",
                    operation="runReport",
                    body={
                        "dimensions": [{"name": "notARealDimension"}],
                        "metrics": [{"name": "activeUsers"}],
                        "dateRanges": [{"startDate": "7daysAgo", "endDate": "yesterday"}],
                    },
                ),
                Guardrails(row_cap=10, timeout_s=30),
                IDENTITY,
            )
        assert excinfo.value.capability_code == "schema_mismatch"


# --- GSC --------------------------------------------------------------------


@pytest.mark.gsc_live
@pytest.mark.skipif(
    not os.environ.get("CTXLAYER_GSC_LIVE"),
    reason="set CTXLAYER_GSC_LIVE=1, CTXLAYER_GSC_SITE_URL, GOOGLE_APPLICATION_CREDENTIALS",
)
class TestLiveGSCExecution:
    @staticmethod
    def config():
        return {
            "system": "gsc",
            "mode": "api",
            "site_url": os.environ["CTXLAYER_GSC_SITE_URL"],
            "credentials_file": os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        }

    def executor(self):
        from connectors.gsc.executor import GscExecutor

        return GscExecutor()

    def test_search_analytics_query_for_documented_fields(self):
        result = self.executor().execute(
            self.config(),
            ExecuteRequest(
                dialect="api",
                operation="searchAnalytics.query",
                body={
                    "startDate": "2026-06-01",
                    "endDate": "2026-06-30",
                    "dimensions": ["query"],
                },
            ),
            Guardrails(row_cap=25, timeout_s=30),
            IDENTITY,
        )
        assert [c["name"] for c in result.columns][:1] == ["query"]
        print(f"\n[live] GSC query: {result.row_count} rows, first={result.rows[:2]}")

    def test_undocumented_dimension_refused_before_the_wire(self):
        with pytest.raises(GuardrailViolation) as excinfo:
            self.executor().execute(
                self.config(),
                ExecuteRequest(
                    dialect="api",
                    operation="searchAnalytics.query",
                    body={
                        "startDate": "2026-06-01",
                        "endDate": "2026-06-30",
                        "dimensions": ["query", "browser"],
                    },
                ),
                Guardrails(row_cap=10, timeout_s=30),
                IDENTITY,
            )
        assert excinfo.value.capability_code == "schema_mismatch"
        assert "browser" in excinfo.value.detail["undocumented_dimensions"]
