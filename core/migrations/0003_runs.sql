-- Drift-run records (sync orchestrator spec §5 stage 11). Written by the
-- CP-3b orchestrator; the table ships now so the ops schema is complete
-- (CP-3a ruling E1).

CREATE TABLE runs (
    run_id                text PRIMARY KEY,       -- ULID (sync §5 stage 1)
    triggers              jsonb NOT NULL,         -- coalesced trigger set
    systems               jsonb NOT NULL,         -- {included: [], excluded: [{system, reason}]}
    kb_ref                text NOT NULL,          -- pinned merged-HEAD commit
    snapshot_refs         jsonb NOT NULL,         -- per-system accepted snapshot ids (new + baseline)
    classification_counts jsonb,
    contaminated_docs     jsonb,
    outcome               text NOT NULL CHECK (outcome IN
        ('succeeded', 'no-op', 'failed', 'failed_acquisition', 'retry_head_moved')),
    pr_url                text,
    started_at            timestamptz NOT NULL,
    finished_at           timestamptz,
    duration_ms           integer
);

CREATE INDEX runs_by_time ON runs (started_at DESC);
