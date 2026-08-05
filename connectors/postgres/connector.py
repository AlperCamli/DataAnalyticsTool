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
from connectors.postgres.executor import PostgresExecutor, RoleCheckFailed


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


def check_introspection_role(conn: psycopg.Connection) -> dict:
    """Refuse to introspect as a superuser-class role (D-71.2, F3).

    Introspection reads `pg_catalog`, which is world-readable and not
    privilege-filtered — so it needs neither SUPERUSER nor BYPASSRLS,
    and holding them buys nothing while costing the RLS guarantee for
    anything that later reads rows over this connection.

    Checked at the start of every live snapshot job rather than once at
    process start: the DSN is per-system and resolved at job time (J-4),
    so "startup" for this connection *is* the job. Returns the role
    facts on success; raises `RoleCheckFailed` naming the attributes
    otherwise. Failing the whole job is correct under S-6 — a snapshot
    is all-or-nothing, and one taken over an over-privileged connection
    is not a snapshot we want to accept.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_user, rolsuper, rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        )
        row = cur.fetchone()
        if row is None:
            raise RoleCheckFailed("cannot read pg_roles for the current introspection role")
        role, is_super, bypass_rls = row

    held = [name for name, value in (("SUPERUSER", is_super), ("BYPASSRLS", bypass_rls)) if value]
    if held:
        raise RoleCheckFailed(
            f"introspection role {role!r} holds {', '.join(held)}; introspection reads "
            "pg_catalog and requires neither (D-71.2). Provision the dedicated role with "
            "deploy/introspection-role.sql and point config.dsn/dsn_env at it. "
            "Refusing to introspect."
        )
    return {"role": role, "superuser": is_super, "bypassrls": bypass_rls}


class PostgresMetadata(MetadataProvider):
    def preflight(self, config: dict) -> dict:
        """Connect as the introspection role and read it back.

        Exactly the first two things a live snapshot job does — resolve
        the DSN the same way, connect through the same `_connect` (whose
        error mapping is what turns a refused password into `auth_error`
        and therefore into the operator's re-auth prompt), and run the
        same D-71.2 role check. Nothing beyond that: a probe is not a
        small snapshot.

        In `ddl-file` mode there is no customer connection to test — the
        source is a set of files and an ephemeral container — so the
        probe checks the files exist and says plainly that it tested no
        credential, rather than booting a container to manufacture a
        green tick.
        """
        if config.get("mode") == "ddl-file":
            files = [Path(p) for p in config.get("ddl_files") or []]
            missing = [str(p) for p in files if not p.is_file()]
            if missing:
                raise ConfigError(f"DDL files not found: {', '.join(missing)}")
            return {
                "probed": True,
                "mode": "ddl-file",
                "ddl_files": len(files),
                "credential_tested": False,
                "note": "ddl-file mode reads local files; no source credential exists to test",
            }
        with _connect(self._live_dsn(config)) as conn:
            facts = check_introspection_role(conn)
        return {"probed": True, "mode": "live", "credential_tested": True, **facts}

    def introspect(self, config: dict) -> IntrospectionResult:
        schemas = config.get("schemas")
        if config["mode"] == "live":
            # The role check applies to the *customer's* connection only.
            objects, props = self._introspect_dsn(
                self._live_dsn(config), schemas, check_role=True
            )
        else:  # "ddl-file" — the config schema admits no other mode
            ddl_files = [Path(p) for p in config["ddl_files"]]
            missing = [str(p) for p in ddl_files if not p.is_file()]
            if missing:
                raise ConfigError(f"DDL files not found: {', '.join(missing)}")
            with ephemeral_postgres(config["image"]) as (container, dsn):
                apply_ddl(container, ddl_files)
                # Deliberately unchecked: this is our own throwaway
                # container, and applying the customer's DDL *requires*
                # the superuser the check would refuse. Nothing customer-
                # owned is reachable from it.
                objects, props = self._introspect_dsn(dsn, schemas, check_role=False)
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
    def _introspect_dsn(
        dsn: str, schemas: list[str] | None, *, check_role: bool
    ) -> tuple[list[dict], dict]:
        with _connect(dsn) as conn:
            if check_role:
                check_introspection_role(conn)
            try:
                return introspect_connection(conn, schemas)
            except psycopg.OperationalError as exc:
                # Mid-run connection loss: the whole job fails (S-6) and
                # retries later; nothing partial ever leaves this frame.
                raise SourceUnavailable(f"lost postgres connection mid-introspection: {exc}") from exc


connector = Connector(
    manifest=Path(__file__).parent / "connector.yaml",
    handlers={"metadata": PostgresMetadata(), "query": PostgresExecutor()},
)
