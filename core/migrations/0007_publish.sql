-- CP-7 (M3): publish persistence (formats spec §4.6, F-5/F-6/FM-3) and
-- the gateway lineage attestations that feed the next graph
-- regeneration (F-3/F-4).

-- Every revision of every published artifact, kept forever (FM-3: they
-- are audit evidence). Identity is the artifact's stable id (F-5 —
-- UUID-based string minted by the report skill); revision is
-- server-assigned, monotonic per artifact; content_hash is change
-- detection only, computed server-side over the canonical body.
-- Drafts never persisted here (F-6: pre-publish drafts are
-- session-local).
CREATE TABLE report_artifacts (
    artifact_id  text NOT NULL,
    revision     integer NOT NULL CHECK (revision >= 1),
    content_hash text NOT NULL,
    body         jsonb NOT NULL,
    created_by   text NOT NULL,
    kb_ref       text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, revision)
);
CREATE INDEX ON report_artifacts (artifact_id, content_hash);

-- One row per (artifact, target): the §8.2 result of the most recent
-- publish. Same id + unchanged content_hash short-circuits to this row
-- (§4.6); a new hash re-publishes and updates it (PB-2: update, never
-- duplicate).
CREATE TABLE publish_results (
    artifact_id  text NOT NULL,
    target       text NOT NULL,
    revision     integer NOT NULL,
    content_hash text NOT NULL,
    result       jsonb NOT NULL,
    audit_ref    uuid,
    job_id       text,
    published_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_id, target)
);

-- Gateway-observed lineage attestations (F-3: tier pipeline-tool, ref
-- "gateway:<audit-id>"; F-4: published reports become graph nodes).
-- The drift pipeline exports these to `python -m lineage
-- --attestations` at the next regeneration; they are never marked
-- consumed — the graph build is deterministic over ALL of them, and
-- requiredness is "any attestation whose edge is not yet in the HEAD
-- graph".
CREATE TABLE lineage_attestations (
    source_fqn  text NOT NULL,
    target_fqn  text NOT NULL,
    operation   text NOT NULL,
    evidence    jsonb NOT NULL,
    source_meta jsonb,
    target_meta jsonb,
    audit_ref   uuid,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_fqn, target_fqn, operation)
);
