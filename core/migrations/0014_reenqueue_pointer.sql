-- B-1 finding B1-F1: the re-enqueue pointer does not belong inside the
-- error object.
--
-- The first cut wrote `error.reenqueued_as` onto the dead job — which
-- put a non-error fact inside the field that holds why the job died, so
-- an operator reading a failure found a success pointer mixed into it.
-- (Caught by the operator on the gate demo's act 3, in those words.)
--
-- Its own column, and the existing rows moved rather than left behind:
-- a record half in one place and half in another is the fan-out shape,
-- and there are only a handful of rows to carry over.
ALTER TABLE jobs ADD COLUMN reenqueued_as text;

UPDATE jobs
   SET reenqueued_as = error->>'reenqueued_as',
       error = error - 'reenqueued_as'
 WHERE error ? 'reenqueued_as';

-- One dead job points at one replacement. A second press on the same
-- dead row is an operator pressing the wrong one — the chain continues
-- from the newest job, not from the original — and the UI now says so
-- rather than silently starting a parallel branch.
CREATE INDEX ON jobs (reenqueued_as) WHERE reenqueued_as IS NOT NULL;
