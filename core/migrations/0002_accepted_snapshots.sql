-- Accepted snapshots (J-6 passed): the store the sync engine's diff
-- baseline reads (sync spec §3). `body` is the §6 canonical
-- serialization exactly as the Python delivery gate wrote it —
-- byte-authoritative, never re-serialized by the core. Retention is
-- last 10 per system (JP-3), pruned on insert.

CREATE TABLE accepted_snapshots (
    snapshot_id           text PRIMARY KEY,       -- ULID
    system                text NOT NULL,
    job_id                text REFERENCES jobs (job_id),
    snapshot_version      text NOT NULL,
    source_mode           text NOT NULL,
    connector_name        text NOT NULL,
    connector_version     text NOT NULL,
    captured_at           timestamptz NOT NULL,
    body                  bytea NOT NULL,
    sha256                text NOT NULL,
    canonical_body_sha256 text NOT NULL,          -- the S-3/§7 diff-identity hash
    object_count          integer NOT NULL,
    accepted_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX accepted_snapshots_by_system
    ON accepted_snapshots (system, accepted_at DESC);
