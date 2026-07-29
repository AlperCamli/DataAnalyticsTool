-- CP-7 (M3, ruling D-91): the two-call publish contract's server-side
-- records (report-authoring spec §7, MCP §6.8 amendment).

-- Latest successful model delivery per (artifact, target), superseded
-- on the next successful delivery. `results` retains the
-- gateway-executed rows that fed the model — the restore source that
-- makes the NEXT delivery complete-or-previous (capability §8.2
-- `previous`, AT-8); exec-role reporting-view aggregates only, same
-- trust zone as the audit text. `tables` is the schema as delivered —
-- what the authoring skill built field references against.
CREATE TABLE model_deliveries (
    artifact_id  text NOT NULL,
    target       text NOT NULL,
    revision     integer NOT NULL CHECK (revision >= 1),
    content_hash text NOT NULL,
    workspace_id text NOT NULL,
    dataset_id   text NOT NULL,
    tables       jsonb NOT NULL,
    results      jsonb NOT NULL,
    audit_ref    uuid,
    job_id       text,
    delivered_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, target)
);

-- The F-4-style permanent record: one row per attested revision.
-- Re-attesting the same {artifact_id, target, revision} updates the
-- same row (capability §8.2 amendment). A delivery whose revision has
-- no row here is delivered-but-unattested — the loud dangling state
-- `cli publish deliveries` lists (MCP §6.8 amendment).
CREATE TABLE report_attestations (
    artifact_id     text NOT NULL,
    target          text NOT NULL,
    revision        integer NOT NULL CHECK (revision >= 1),
    workspace_id    text NOT NULL,
    dataset_id      text NOT NULL,
    report_id       text NOT NULL,
    definition_hash text NOT NULL,
    verified_at     timestamptz NOT NULL,
    attested_at     timestamptz NOT NULL DEFAULT now(),
    audit_ref       uuid,
    job_id          text,
    PRIMARY KEY (artifact_id, target, revision)
);
