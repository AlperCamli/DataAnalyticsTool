-- CP-4 (M1): MCP audit contract (MCP spec §8, MCP-R13), fault ledger
-- (ledger spec §3), class-1 detector rules as ops config (L-3), routing
-- table (§7), validation-token signing keys (MCP §5), and a small kv
-- table for sweep cursors.

-- One record per MCP call, including denied/filtered decisions (M-8).
-- args_digest is a hash; full statement text is stored only for
-- validate/execute/publish (§8) — this table is the restricted deep
-- store the ledger's audit_ref points into (L-8).
CREATE TABLE audit_records (
    audit_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts           timestamptz NOT NULL DEFAULT now(),
    subject      text NOT NULL,
    roles        text[] NOT NULL DEFAULT '{}',
    profile      text,
    session_id   text,
    tool         text NOT NULL,
    args_digest  text NOT NULL,
    kb_ref       text,
    snapshot_ref jsonb,
    decision     text NOT NULL CHECK (decision IN ('allowed', 'denied', 'filtered')),
    decision_reason text,
    duration_ms  integer,
    result_meta  jsonb NOT NULL DEFAULT '{}'::jsonb,
    statement_text text
);
CREATE INDEX ON audit_records (ts);
CREATE INDEX ON audit_records (subject, ts);
CREATE INDEX ON audit_records (tool, ts);

-- Fault ledger (ledger spec §3.1/§3.2) — issues first (events reference
-- them). DDL is the spec's, verbatim in shape.
CREATE TABLE ledger_issues (
    issue_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint   text UNIQUE NOT NULL,
    kind          text NOT NULL,
    system        text,
    object_fqn    text,
    title         text NOT NULL,
    status        text NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'triaged', 'resolved', 'dismissed')),
    routed_to     text NOT NULL,
    first_seen    timestamptz NOT NULL,
    last_seen     timestamptz NOT NULL,
    occurrences   integer NOT NULL DEFAULT 1,
    distinct_subjects integer NOT NULL DEFAULT 0,
    reopen_count  integer NOT NULL DEFAULT 0,
    resolved_at   timestamptz,
    resolved_by   text,
    resolution    jsonb,
    links         jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX ON ledger_issues (status, occurrences DESC, last_seen DESC);
CREATE INDEX ON ledger_issues (object_fqn) WHERE object_fqn IS NOT NULL;

CREATE TABLE ledger_events (
    event_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ts            timestamptz NOT NULL DEFAULT now(),
    detector_class smallint NOT NULL CHECK (detector_class IN (1, 2, 3)),
    kind          text NOT NULL,
    fingerprint   text NOT NULL,
    system        text,
    object_fqn    text,
    subject       text,
    session_id    text,
    profile       text,
    audit_ref     uuid,
    kb_ref        text,
    snapshot_ref  jsonb,
    description   text,
    detail        jsonb NOT NULL DEFAULT '{}'::jsonb,
    issue_id      uuid NOT NULL REFERENCES ledger_issues (issue_id)
);
CREATE INDEX ON ledger_events (issue_id, ts);
CREATE INDEX ON ledger_events (ts);
CREATE INDEX ON ledger_events (fingerprint, ts);

-- Class-1 detector rules are configuration data, not code (L-3):
-- shipped defaults per ledger spec §5, editable without deploy (FL-9).
CREATE TABLE detector_rules (
    rule    text PRIMARY KEY,
    enabled boolean NOT NULL,
    config  jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO detector_rules (rule, enabled, config) VALUES
  ('zero_result_search',        true,  '{"mode":"sync","kind":"coverage_gap"}'),
  ('repeated_validate_fail',    true,  '{"mode":"window","kind":"doc_schema_mismatch","threshold":3,"window_h":24}'),
  ('guardrail_pattern',         true,  '{"mode":"window","kind":"guardrail_hit","threshold":3,"window_h":24,"codes":["timeout","row_cap","quota_exhausted"]}'),
  ('abandoned_journey',         true,  '{"mode":"sweep","kind":"abandoned_journey","inactivity_min":30,"min_occurrences":2}'),
  ('execute_without_resolution',false, '{"mode":"sweep","kind":"other","log_only":true}'),
  ('schema_mismatch_at_execute',true,  '{"mode":"sync","kind":"doc_schema_mismatch"}');

-- kind → role routing (ledger §7): shipped default routes everything to
-- the data-team role; benchmark_regression also notifies the author
-- (notification is a dashboard concern; the route row records intent).
CREATE TABLE ledger_routing (
    kind      text PRIMARY KEY,
    routed_to text NOT NULL
);
INSERT INTO ledger_routing (kind, routed_to) VALUES
  ('__default__', 'data-team'),
  ('benchmark_regression', 'data-team+author');

-- Validation-token signing keys (MCP §5: server-signed, key in ops
-- Postgres, rotated by inserting a new active row; verification accepts
-- any stored key by kid so unexpired tokens survive rotation).
CREATE TABLE signing_keys (
    kid        text PRIMARY KEY,
    secret     text NOT NULL,
    active     boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Sweep cursors and other small orchestration state for the MCP layer
-- (e.g. the CL-Resolves merged-PR poll cursor, LED-R4).
CREATE TABLE mcp_state (
    key   text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
