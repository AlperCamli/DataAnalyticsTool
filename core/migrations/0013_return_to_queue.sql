-- B-1: the `batched → approved` return the fault-ledger §4 amendment's
-- state diagram already specifies — "undraftable → returns with the
-- skill's note" — which had no mechanism until now.
--
-- Why a column rather than an event: recording the return as a
-- `ledger_events` row would increment `occurrences`, and occurrences is
-- the demand signal the queue is *ordered* by. A skill saying "I could
-- not write this" would then read as another person asking for it, which
-- is the opposite of what happened. The note belongs to the issue's
-- lifecycle, beside the verdict columns, not to its evidence stream.
--
-- NULL for every other kind and for every request that never came back,
-- exactly as the D-101.2 verdict columns are.
ALTER TABLE ledger_issues ADD COLUMN return_note text;
ALTER TABLE ledger_issues ADD COLUMN returned_at timestamptz;
