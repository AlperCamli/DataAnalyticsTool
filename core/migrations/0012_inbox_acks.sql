-- B-1 (Phase 2, Track B): the F-10 reply path's "seen" state, per the
-- UI-D ruling (D-103.2) that fixed the mechanism as a dashboard badge on
-- the filer's next session.
--
-- The badge counts the issues a caller filed that reached a terminal
-- verdict — `rejected` with its reason, `resolved` with its PR — since
-- that caller last acknowledged them. "Since" has to be server state:
-- the client persists nothing (D-103.1), so a badge computed in the
-- browser would reappear on every reload, in every tab, and would be
-- wrong on a second machine. One row per (subject, issue) acknowledged.
--
-- Deliberately NOT a column on `ledger_issues`: an issue can have many
-- filers (dedup is the point — `occurrences=11` is eleven people), and
-- each of them acknowledges their own copy of the news. A column would
-- let the first reader mark it seen for everybody.
CREATE TABLE dashboard_inbox_acks (
    subject   text NOT NULL,
    issue_id  uuid NOT NULL REFERENCES ledger_issues (issue_id) ON DELETE CASCADE,
    -- What was acknowledged, not merely that something was: an issue
    -- rejected, refiled and rejected again is new news, and comparing
    -- the stored verdict time against the issue's current one is what
    -- makes the badge fire a second time.
    acked_verdict_at timestamptz,
    acked_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (subject, issue_id)
);
CREATE INDEX ON dashboard_inbox_acks (subject);
