"""The static demo MetadataProvider.

The "source" is two hardcoded objects (a table and a view over it), so
the same source state is trivially guaranteed across runs — the C-2
byte-identity check exercises the harness alone. `config.inject_failure`
raises mid-introspection (after the first object is built) to stage
S-6: a failed job must emit nothing, never a one-object snapshot.

Documented source_properties keys (MP-2): `engine` (constant
"static-demo"). Additive only.
"""

from pathlib import Path

from connectors.sdk import (
    Connector,
    IntrospectionResult,
    MetadataProvider,
    QuotaExceeded,
    SourceUnavailable,
)


def _users_table() -> dict:
    return {
        "kind": "table",
        "schema": "public",
        "name": "users",
        "description": "Demo user directory.",
        "columns": [
            {"name": "id", "type": "uuid", "nullable": False,
             "default": "gen_random_uuid()", "ordinal": 1, "description": None},
            {"name": "email", "type": "text", "nullable": False,
             "default": None, "ordinal": 2, "description": "login email"},
            {"name": "created_at", "type": "timestamptz", "nullable": False,
             "default": "now()", "ordinal": 3, "description": None},
        ],
        "keys": {"primary": ["id"], "unique": [["email"]]},
        "stats": {"row_estimate": 3},
    }


def _emails_view() -> dict:
    return {
        "kind": "view",
        "schema": "public",
        "name": "v_user_emails",
        "description": None,
        "columns": [
            {"name": "id", "type": "uuid", "nullable": True,
             "default": None, "ordinal": 1, "description": None},
            {"name": "email", "type": "text", "nullable": True,
             "default": None, "ordinal": 2, "description": None},
        ],
        "keys": {},
        "stats": {"definition": " SELECT users.id,\n    users.email\n   FROM public.users;"},
    }


class StaticDemoMetadata(MetadataProvider):
    def introspect(self, config: dict) -> IntrospectionResult:
        objects = [_users_table()]
        inject = config.get("inject_failure")
        if inject == "source_unavailable":
            raise SourceUnavailable("injected mid-introspection failure (demo)")
        if inject == "internal":
            raise RuntimeError("injected unhandled exception (demo)")
        if inject == "quota":
            raise QuotaExceeded("injected quota exhaustion (demo)", retry_after_s=3600)
        objects.append(_emails_view())
        return IntrospectionResult(
            system_class="sql",
            objects=objects,
            source_properties={"engine": "static-demo"},
        )


connector = Connector(
    manifest=Path(__file__).parent / "connector.yaml",
    handlers={"metadata": StaticDemoMetadata()},
)
