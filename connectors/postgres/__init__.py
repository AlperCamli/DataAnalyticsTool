"""Supabase/Postgres connector (task 1.2, plan §3.1).

One introspector over pg_catalog, two input modes (ddl-file, live), one
output: the normalized snapshot. See connector.py for the provider and
README.md for config, documented source_properties keys, and the
determinism rules this connector pins (DECISIONS.md D-16..D-21).
"""
