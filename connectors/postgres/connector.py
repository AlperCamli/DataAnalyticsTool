"""The Supabase/Postgres MetadataProvider (task 1.2, plan §3.1).

One introspector (catalog.py), two ways to obtain the connection:
ddl-file boots an ephemeral container and executes the customer's DDL
inside it (ephemeral.py); live connects to the configured DSN. The
requested mode is never satisfied any other way (MP-1): an unreachable
DSN or missing Docker fails `source_unavailable`, with no fallback.

Documented source_properties keys (MP-2, additive only):
- `server_version` — "major.minor", derived from `server_version_num`.

Live credentials: `dsn` inline or `dsn_env` (environment indirection,
keeping secrets out of config files). Vault-reference resolution stays
a job-transport concern (DECISIONS.md D-14). Error messages never echo
the DSN — it may carry a password (JC-8).
"""

import os
from pathlib import Path

import psycopg

from connectors.sdk import (
    AuthError,
    ConfigError,
    Connector,
    IntrospectionResult,
    MetadataProvider,
    SourceUnavailable,
)
from connectors.postgres.catalog import introspect_connection
from connectors.postgres.ephemeral import apply_ddl, ephemeral_postgres


def _connect(dsn: str) -> psycopg.Connection:
    try:
        return psycopg.connect(
            dsn, autocommit=True, application_name="contextlayer-postgres"
        )
    except psycopg.ProgrammingError as exc:
        # A malformed-DSN message can echo the DSN itself; never forward it.
        raise ConfigError("invalid postgres DSN (not echoed; check the config)") from exc
    except psycopg.OperationalError as exc:
        message = str(exc)  # libpq redacts passwords from its errors
        if "password" in message or "authentication" in message:
            raise AuthError(
                "postgres authentication failed (check the read-only role credentials)"
            ) from exc
        raise SourceUnavailable(f"cannot reach postgres: {message}") from exc


class PostgresMetadata(MetadataProvider):
    def introspect(self, config: dict) -> IntrospectionResult:
        schemas = config.get("schemas")
        if config["mode"] == "live":
            objects, props = self._introspect_dsn(self._live_dsn(config), schemas)
        else:  # "ddl-file" — the config schema admits no other mode
            ddl_files = [Path(p) for p in config["ddl_files"]]
            missing = [str(p) for p in ddl_files if not p.is_file()]
            if missing:
                raise ConfigError(f"DDL files not found: {', '.join(missing)}")
            with ephemeral_postgres(config["image"]) as (container, dsn):
                apply_ddl(container, ddl_files)
                objects, props = self._introspect_dsn(dsn, schemas)
        return IntrospectionResult(
            system_class="sql", objects=objects, source_properties=props
        )

    @staticmethod
    def _live_dsn(config: dict) -> str:
        if "dsn" in config:
            return config["dsn"]
        env_var = config["dsn_env"]
        dsn = os.environ.get(env_var)
        if not dsn:
            raise ConfigError(f"environment variable {env_var!r} (config.dsn_env) is unset or empty")
        return dsn

    @staticmethod
    def _introspect_dsn(dsn: str, schemas: list[str] | None) -> tuple[list[dict], dict]:
        with _connect(dsn) as conn:
            try:
                return introspect_connection(conn, schemas)
            except psycopg.OperationalError as exc:
                # Mid-run connection loss: the whole job fails (S-6) and
                # retries later; nothing partial ever leaves this frame.
                raise SourceUnavailable(f"lost postgres connection mid-introspection: {exc}") from exc


connector = Connector(
    manifest=Path(__file__).parent / "connector.yaml",
    handlers={"metadata": PostgresMetadata()},
)
