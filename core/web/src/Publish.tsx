/**
 * Publish deliveries (dashboard spec §3, U-9 / F-15 / F-17).
 *
 * The API shipped at B-0; this is its face. Per artifact and target:
 * what was delivered, what was attested, and the **dangling** state
 * F-15 named — a revision delivered to a BI tool with no attestation
 * recording it, which means the two-call publish contract stopped
 * between its two calls. That state is the reason this view exists, so
 * it is the loudest thing on the screen rather than a column somebody
 * has to notice.
 */

import React, { useCallback, useEffect, useState } from "react";
import { api, type ApiError, type Delivery, type DeliveryList } from "./api";
import { Dark, ServerSays, Spinner, Text } from "./ui";

function stamp(iso: string | null): string {
  if (!iso) return "—";
  const t = Date.parse(iso);
  return Number.isFinite(t) ? new Date(t).toISOString().replace("T", " ").slice(0, 19) + "Z" : iso;
}

function DeliveryCard({ row }: { row: Delivery }) {
  return (
    <section className={`deliver-card${row.dangling ? " dangling" : ""}`}>
      <header>
        <h3>
          <code>
            <Text value={row.artifact_id} />
          </code>
        </h3>
        <span className="muted">
          → <Text value={row.target} /> · revision <Text value={row.delivery.revision} />
        </span>
      </header>

      {row.dangling && (
        <div className="notice warn">
          <strong>Delivered, never attested.</strong> Revision{" "}
          <Text value={row.delivery.revision} /> reached <Text value={row.target} /> and no
          attestation records it. Publishing is two calls — deliver, then attest — so this is the
          shape of one that stopped in between: the report exists in the BI tool, and nothing here
          can say what definition produced it.
        </div>
      )}

      <dl className="facts">
        <div>
          <dt>delivered</dt>
          <dd>{stamp(row.delivery.delivered_at)}</dd>
        </div>
        <div>
          <dt>by</dt>
          <dd>
            <Text value={row.subject} />
          </dd>
        </div>
        <div>
          <dt>content hash</dt>
          <dd>
            <code>
              <Text value={row.delivery.content_hash.slice(0, 16)} />
            </code>
          </dd>
        </div>
        <div>
          <dt>workspace</dt>
          <dd>
            <Text value={row.delivery.workspace_id} />
          </dd>
        </div>
        <div>
          <dt>dataset</dt>
          <dd>
            <Text value={row.delivery.dataset_id} />
          </dd>
        </div>
      </dl>

      <div className="attestations">
        <span className="label">attestation history</span>
        {row.attestations.length === 0 ? (
          <span className="muted">none — nothing has been attested for this artifact and target</span>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>rev</th>
                <th>report</th>
                <th>definition hash</th>
                <th>verified</th>
                <th>attested</th>
              </tr>
            </thead>
            <tbody>
              {row.attestations
                .slice()
                .sort((a, b) => b.revision - a.revision)
                .map((att) => (
                  <tr key={`${att.revision}-${att.report_id}`}>
                    <td>
                      <Text value={att.revision} />
                    </td>
                    <td>
                      <code>
                        <Text value={att.report_id} />
                      </code>
                    </td>
                    {/* F-17: what changed in this revision is a hash
                        comparison, and the hashes are here to make it. */}
                    <td>
                      <code>
                        <Text value={att.definition_hash.slice(0, 16)} />
                      </code>
                    </td>
                    <td>{stamp(att.verified_at)}</td>
                    <td>{stamp(att.attested_at)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

export function Publish() {
  const [list, setList] = useState<DeliveryList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const res = await api.get<DeliveryList>("/v1/dashboard/deliveries?limit=50");
    setLoading(false);
    if (!res.ok) {
      setError(res.error);
      setList(null);
      return;
    }
    setError(null);
    setList(res.data);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <Spinner label="reading deliveries…" />;
  if (error) return <ServerSays error={error} />;
  if (!list) return null;

  const dangling = list.rows.filter((r) => r.dangling).length;

  return (
    <div className="publish">
      {list.scope.role_scope === "self" && (
        <div className="notice">
          You are seeing <strong>the reports you published</strong>. The server scopes this list to
          your own identity.
        </div>
      )}

      {list.rows.length === 0 ? (
        // UI-10: the honest pre-first-publish state, named rather than
        // filled with a sample row.
        <Dark
          title="Nothing has been published yet"
          why="No report artifact has been delivered to a BI target from this estate. When one is, its deliveries and attestations appear here."
        />
      ) : (
        <>
          <p className="muted">
            <Text value={list.rows.length} /> delivery row(s)
            {dangling > 0 ? (
              <>
                {" · "}
                <strong className="bad">
                  <Text value={dangling} /> delivered but never attested
                </strong>
              </>
            ) : null}
          </p>
          {list.rows.map((row) => (
            <DeliveryCard key={`${row.artifact_id}-${row.target}-${row.delivery.revision}`} row={row} />
          ))}
        </>
      )}
    </div>
  );
}
