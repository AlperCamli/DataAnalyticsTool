-- B-0 (Phase 2, Track B): browser session auth (D-102.1) and the ledger
-- verdict lifecycle the knowledge-request queue runs on (fault-ledger
-- spec §4 amendment, D-101.2). Additive throughout.

-- Server-side browser sessions (D-102.1). The cookie carries an opaque
-- id; only its sha256 is stored, so a read of this table yields no
-- usable cookie. The IdP access token is held here rather than in the
-- browser precisely so the browser never holds a bearer credential —
-- identity is still resolved per request through the same verifier the
-- MCP path uses (OidcClient.resolveIdentity), so an IdP-side revocation
-- takes effect on the very next dashboard call (MCP-R1/MT-9 semantics,
-- inherited rather than re-implemented).
CREATE TABLE dashboard_sessions (
    session_hash  text PRIMARY KEY,
    subject       text NOT NULL,
    access_token  text NOT NULL,
    refresh_token text,
    -- Double-submit CSRF secret: useless without the cookie, so it is
    -- readable by the SPA (GET /v1/auth/session) and required on every
    -- cookie-authenticated write.
    csrf_token    text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    last_seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON dashboard_sessions (expires_at);
CREATE INDEX ON dashboard_sessions (subject);

-- In-flight authorization-code grants: PKCE verifier + the post-login
-- path, keyed by the hashed `state`. Short-lived and single-use — the
-- callback deletes the row before it exchanges the code, so a replayed
-- callback finds nothing.
CREATE TABLE dashboard_auth_states (
    state_hash    text PRIMARY KEY,
    code_verifier text NOT NULL,
    redirect_to   text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL
);
CREATE INDEX ON dashboard_auth_states (expires_at);

-- Fault-ledger §4 amendment (D-101.2): the enrichment_request verdict
-- lifecycle. `open → approved | rejected(reason)`, `approved →
-- batched(batch_id) → resolved` on the batch PR's merge via the existing
-- L-5 CL-Resolves path. Every column below is NULL for every other kind,
-- and every other kind's §7 lifecycle is untouched.
ALTER TABLE ledger_issues DROP CONSTRAINT ledger_issues_status_check;
ALTER TABLE ledger_issues ADD CONSTRAINT ledger_issues_status_check
    CHECK (status IN ('open', 'triaged', 'resolved', 'dismissed',
                      'approved', 'rejected', 'batched'));

ALTER TABLE ledger_issues ADD COLUMN verdict_by     text;
ALTER TABLE ledger_issues ADD COLUMN verdict_at     timestamptz;
-- Human-authored text that will be shown to the filer, so LED-R2's
-- scrub and bounds apply to it exactly as to a description.
ALTER TABLE ledger_issues ADD COLUMN verdict_reason text;
ALTER TABLE ledger_issues ADD COLUMN batch_id       text;

CREATE INDEX ON ledger_issues (batch_id) WHERE batch_id IS NOT NULL;
