-- A-1 drill: the revert (D-98.3 — the estate ends byte-identical).
--
-- Applied by the OPERATOR as customer DBA at STOP-3, after same-day
-- evidence extraction (D-96.2). The inverse of a1-drill-rename.sql;
-- ALTER VIEW … RENAME COLUMN preserves grants/reloptions, so after
-- this the canonical snapshot body hash must equal the pre-drill hash
-- — the final sync cycle verifies exactly that.

ALTER VIEW reporting.v_user_signups_by_day
    RENAME COLUMN signup_date TO signup_day;
