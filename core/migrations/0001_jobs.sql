-- Job queue (job protocol §4–§5, §8). The queue is core-internal (J-1):
-- only the job API's observable behavior is normative; this schema may
-- evolve freely behind it.

CREATE TABLE jobs (
    job_id             text PRIMARY KEY,          -- ULID
    type               text NOT NULL,
    class              text NOT NULL CHECK (class IN ('batch', 'interactive')),
    system             text NOT NULL,
    connector_name     text NOT NULL,
    version_constraint text NOT NULL DEFAULT '*',
    payload            jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {config, credentials[]} — references only (J-4)
    priority           integer NOT NULL,
    attempt            integer NOT NULL DEFAULT 1,
    max_attempts       integer NOT NULL,
    deadline_s         integer NOT NULL,
    state              text NOT NULL CHECK (state IN
        ('queued', 'leased', 'running', 'succeeded', 'dead_lettered', 'cancelled')),
    not_before         timestamptz NOT NULL DEFAULT now(),
    deferrals          integer NOT NULL DEFAULT 0,
    max_deferrals      integer NOT NULL DEFAULT 20,
    lease_token        text,
    lease_expires_at   timestamptz,
    runner_id          text,
    cancel_requested   boolean NOT NULL DEFAULT false,
    -- Trigger history (§8): merged enqueues append here; triggers->0 is
    -- the original §4.1 trigger.
    triggers           jsonb NOT NULL DEFAULT '[]'::jsonb,
    progress           jsonb,
    error              jsonb,                     -- last §6.5 error envelope
    result             jsonb,                     -- non-snapshot results (inline)
    result_meta        jsonb,                     -- snapshot: accepted-snapshot ref
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    started_at         timestamptz,
    finished_at        timestamptz
);

-- §8 dedupe: at most one queued batch job per (system, type). The claim
-- transaction enforces the "at most one running per key" half.
CREATE UNIQUE INDEX jobs_dedupe_queued
    ON jobs (system, type)
    WHERE state = 'queued' AND class = 'batch';

CREATE INDEX jobs_claimable
    ON jobs (priority, created_at)
    WHERE state = 'queued';

CREATE INDEX jobs_leased
    ON jobs (lease_expires_at)
    WHERE state IN ('leased', 'running');
