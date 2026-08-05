-- D-106.2 — the defer/dedupe collision. A leased batch job that defers
-- while a duplicate for its (system, type) already sits queued cannot
-- return to `queued`: the §8 partial unique index holds exactly one
-- queued batch job per key. Nothing failed, so dead-lettering it would
-- be a lie; the ruling is COALESCE — the deferred instance terminates
-- here, the queued job survives and adopts the later `not_before`.
--
-- `coalesced` is a terminal state distinct from `succeeded` (no work
-- was delivered), `cancelled` (nobody cancelled it) and `dead_lettered`
-- (nothing failed). Additive: no existing row changes state, and every
-- other transition is untouched (job spec §4.3 amendment, D-106.2).

ALTER TABLE jobs DROP CONSTRAINT jobs_state_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_state_check CHECK (state IN
    ('queued', 'leased', 'running', 'succeeded', 'dead_lettered',
     'cancelled', 'coalesced'));
