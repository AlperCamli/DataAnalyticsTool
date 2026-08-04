-- A-1 drill: the staged breaking change (D-98.3; playbook gate item 7,
-- human half — first-ever rehearsal).
--
-- ONE reporting view, ONE column rename: `signup_day` → `signup_date`
-- on reporting.v_user_signups_by_day. Same type (date), same ordinal
-- (1), new name — the exact shape the diff classifies as a rename
-- candidate with both interpretations, breaking under both readings.
--
-- Applied by the OPERATOR as customer DBA (D-81 discipline: the session
-- drafts DDL, never runs it against the estate). ALTER VIEW … RENAME
-- COLUMN preserves grants, ownership, and reloptions
-- (security_barrier), so the paired revert (a1-drill-revert.sql)
-- returns the catalog byte-identical — verified afterward by canonical
-- snapshot body hash (S-3).
--
-- Expected contamination: systems/supabase/reporting/
-- v_user_signups_by_day.md (the PR #26 enrichment; its `object:`
-- front-matter is a declared dependency per the scan). Downstream, the
-- lineage walk reaches the Looker report node tl-4ea06a83615531cd,
-- which has no doc — no further contamination.

ALTER VIEW reporting.v_user_signups_by_day
    RENAME COLUMN signup_day TO signup_date;
