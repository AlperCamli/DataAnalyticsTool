# D-72.4 — Onboarding playbook: credential assertions at the readiness gate

Spec-only PR. Authorized by ruling **D-72 point 4** as one additive
amendment to `specs/customer-onboarding-playbook.md`; nothing else in the
spec set is touched and no code changes. It is deliberately separate from
the D-71 F2/F3 code PR — the ruling asked for the spec diff to lead its
own small PR.

## The diff

**§13 (Step 9 — readiness gate)** gains item **9**, three role/credential
assertions, each verified by attribute:

| Identity | Assertion | Evidence |
|---|---|---|
| `example_exec` | Read-only at the database level: none of SUPERUSER/CREATEDB/CREATEROLE/BYPASSRLS, no write grant reachable through role membership, no schema CREATE | Executor startup check passes against the configured `execute_dsn` (G3); the file's VERIFY queries return empty |
| `contextlayer_introspect` | Neither SUPERUSER nor BYPASSRLS; no SELECT grant on customer tables | One accepted live snapshot under the role, byte-identical to the previous role's on unchanged source state (D-71.2) |
| `contextlayer-sync` PAT | Fine-grained, single KB repository, contents + pull-request write and nothing else | P-H / D-66.7 |

Three distinct identities with distinct secrets; no DSN is the estate's
default `postgres`.

**§14** gains register item **OB-5** — the pairing motion, filed per
D-72.5.

## Why this belongs on the gate at all

Every other item on the §13 checklist verifies something the *platform*
does: snapshots accepted, KB merged, profiles enforcing, benchmark wired.
These three verify what the **customer's own infrastructure grants us** —
and that is the one layer where a mistake is invisible from inside the
product. No amount of correct code detects an over-privileged role it was
handed; it just quietly has more reach than anyone intended. The gate is
the only place we look.

## The line that does the real work

> *Check attributes, not names.* A managed-Postgres `postgres` role may
> report `rolsuper = false` and still hold BYPASSRLS.

This is not a hypothetical. Measured on the example estate during the F3
build: Supabase's `postgres` reports `rolsuper = false`, `rolcreatedb =
true`, `rolcreaterole = true`, `rolbypassrls = true`. The obvious way to
write both the check and the checklist item — "is this the superuser?" —
would have passed the exact connection F3 was filed about. The
implementation tests both attributes, and it is BYPASSRLS that fires; the
gate item now says so in the spec rather than leaving it as folklore in a
test file.

## OB-5, and what it is not

OB-5 records that a profile granting `execute_sql` must be paired with a
database role scoped no wider than that profile's visible surface. Filed
as an obligation, **not** drafted as a mechanical gate item, because the
mechanical form needs a ruling: D-71.1 made the KB visibility map govern
the execution surface, but the map is our gate and the database role is
the wall, and nothing today checks that the wall matches the gate.

It is not load-bearing yet — the pilot's only execute-granted profile is
Steward at `visibility: ["**"]`, so gate and wall coincide. It becomes
load-bearing at the first customer with more than one execute-granted
profile, which is the first point at which they can diverge. That trigger
is written into the register row rather than left to memory.

## Review notes

- Additive only: item 9 appends, OB-5 appends. No existing gate item,
  register row, or numbering moves.
- The amendment block follows the house convention — dated, attributed to
  the ruling, and carrying its own rationale inline (as in MCP §3/§5/§6.6
  and the KB spec amendments).
- No conformance tests attach to this diff: the assertions it adds are
  operator-verified at a customer gate, and the two role checks behind
  them are already tested where they are enforced
  (`tests/test_execution_role_sql.py`, `tests/test_introspection_role_sql.py`).
