#!/bin/bash
# Extract the M3 gate demo's evidence from the live ops database.
#
# Run on machine 1 AFTER the reporter session on machine 2 finishes:
#
#   results/cp7-gate/extract-audit.sh '2026-07-27T14:00:00Z'
#
# The argument is the demo's start instant (UTC) — everything the
# reporter did after it is captured. Writes four files next to this
# script; they are the committed gate evidence (B.4).
#
# Nothing here is a summary written by an agent: each file is a direct
# dump of what the server recorded, so a reviewer can check the claims
# in the gate note against the rows rather than against prose.
set -euo pipefail
cd "$(dirname "$0")"

SINCE="${1:-}"
if [ -z "$SINCE" ]; then
  echo "usage: $0 <since-utc-iso8601>   e.g. $0 '2026-07-27T14:00:00Z'" >&2
  exit 2
fi

PG="docker exec dataproject-postgres-1 psql -U postgres -d cl_ops"

# 1. The audit chain, in order, as the MCP server wrote it (MCP §7).
#    statement_text is included deliberately: for execute/validate/publish
#    the product spec §8 stores the full text, and the demo's whole claim
#    is that what ran is what the KB grounded.
$PG -At -F'|' -c "
  select ts, tool, decision, coalesce(decision_reason,'-'),
         subject, profile, coalesce(session_id,'-'),
         coalesce(result_meta::text,'-'),
         replace(coalesce(statement_text,'-'), chr(10), ' ')
    from audit_records
   where ts >= '$SINCE'::timestamptz
   order by ts;" > audit-chain.txt

# 2. Same rows as JSON, for anything that needs to parse them.
$PG -At -c "
  select coalesce(jsonb_pretty(jsonb_agg(to_jsonb(a) order by a.ts)), '[]')
    from audit_records a
   where a.ts >= '$SINCE'::timestamptz;" > audit-chain.json

# 3. Fault-ledger events raised during the demo — the flag_gap path
#    (B.3: missing_join_path must be here, not merely refused inline).
$PG -At -F'|' -c "
  select e.ts, e.detector_class, e.kind, e.system, coalesce(e.object_fqn,'-'),
         e.subject, coalesce(e.audit_ref::text,'-'), e.description,
         coalesce(i.status,'-'), coalesce(i.routed_to,'-')
    from ledger_events e
    left join ledger_issues i on i.issue_id = e.issue_id
   where e.ts >= '$SINCE'::timestamptz
   order by e.ts;" > ledger-events.txt

# 4. Publish outcomes: what was created, at which revision, for whom.
$PG -At -c "
  select coalesce(jsonb_pretty(jsonb_agg(to_jsonb(a) order by a.ts)), '[]')
    from audit_records a
   where a.ts >= '$SINCE'::timestamptz and a.tool = 'publish_report';" > publish-results.json

# 5. The two-call publish trail (amended gate, Act 4): per report, the
#    deliver_model/attest pair from audit plus the server's permanent
#    delivery and attestation records. A delivery row with no matching
#    attestation row is the DANGLING state — loud by design.
$PG -At -F'|' -c "
  select a.ts, a.result_meta->>'artifact_id', a.result_meta->>'mode',
         a.decision, coalesce(a.result_meta->>'error','-'),
         coalesce(a.result_meta->>'dataset_id','-')
    from audit_records a
   where a.ts >= '$SINCE'::timestamptz and a.tool = 'publish_report'
   order by a.ts;" > publish-trail.txt
{
  echo "-- model_deliveries --"
  $PG -At -F'|' -c "
    select artifact_id, target, revision, workspace_id, dataset_id, delivered_at
      from model_deliveries order by delivered_at;"
  echo "-- report_attestations --"
  $PG -At -F'|' -c "
    select artifact_id, target, revision, report_id, definition_hash, verified_at, attested_at
      from report_attestations order by attested_at;"
  echo "-- dangling (deliveries whose revision has no attestation) --"
  $PG -At -F'|' -c "
    select d.artifact_id, d.target, d.revision, d.dataset_id
      from model_deliveries d
      left join report_attestations a
        on a.artifact_id = d.artifact_id and a.target = d.target
       and a.revision = d.revision
     where a.report_id is null;"
} >> publish-trail.txt

echo "wrote:"
for f in audit-chain.txt audit-chain.json ledger-events.txt publish-results.json publish-trail.txt; do
  printf '  %-22s %s lines\n' "$f" "$(wc -l < "$f" | tr -d ' ')"
done
echo
echo "Denials in the window (expect the two Act-3 cases):"
grep -c '|denied|' audit-chain.txt || echo "  none — Act-3 evidence is missing"
echo "publish_report mode calls in the window (expect deliver_model+attest per report):"
cut -d'|' -f3 publish-trail.txt 2>/dev/null | grep -c 'deliver_model\|attest' || true
