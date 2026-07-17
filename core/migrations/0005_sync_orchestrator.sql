-- Sync orchestrator (CP-3b): connection registry, per-hook webhook
-- secrets (ruling E2), trigger-pending marks (sync spec §4/§7 coalescing),
-- freshness warning state (§8), and additive run-record columns.

-- The connection registry: what "configured system" means (webhook 404
-- semantics, §4.2) and the job template a trigger enqueues (connector +
-- payload with credential *references* only, J-4). Managed by the admin
-- CLI until the Connections UI arrives with the dashboard (E2).
CREATE TABLE sync_systems (
    system             text PRIMARY KEY,
    connector_name     text NOT NULL,
    version_constraint text NOT NULL DEFAULT '*',
    payload            jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

-- Per-hook shared secrets (§4.2, SY-2). Only the sha256 of the secret is
-- stored; the admin CLI prints the secret exactly once at generation.
-- Rotation is a row update — the endpoint reads per request, so rotation
-- takes effect without restart (CP-3 exit criterion).
CREATE TABLE sync_hooks (
    system      text PRIMARY KEY REFERENCES sync_systems (system) ON DELETE CASCADE,
    secret_hash text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    rotated_at  timestamptz
);

-- Trigger-pending marks (§4: "mark the system trigger-pending for the
-- next run"; §7 coalescing). A run consumes all rows atomically at pin;
-- triggers landing mid-run insert fresh rows that the completion check
-- picks up as exactly one follow-up run (SY-6).
CREATE TABLE sync_pending (
    system     text PRIMARY KEY,
    triggers   jsonb NOT NULL DEFAULT '[]'::jsonb,
    job_id     text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Active freshness warnings (§8, OD-3 mechanism). Presence of a row =
-- warning in force; raise/clear transitions also land in health_events.
CREATE TABLE freshness_warnings (
    system      text PRIMARY KEY,
    raised_at   timestamptz NOT NULL DEFAULT now(),
    age_s       bigint NOT NULL,
    threshold_s bigint NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Run records (§5.11): a `running` outcome so a crashed deployment leaves
-- a visible torso instead of nothing (startup marks stale ones failed),
-- and a detail column for stage/error/exclusion specifics.
ALTER TABLE runs ADD COLUMN detail jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE runs DROP CONSTRAINT runs_outcome_check;
ALTER TABLE runs ADD CONSTRAINT runs_outcome_check CHECK (outcome IN
    ('running', 'succeeded', 'no-op', 'failed', 'failed_acquisition', 'retry_head_moved'));
