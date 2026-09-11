import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";

function fmt(v) {
  return v === null || v === undefined ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function SegmentsSection({ ticker, basis = "consolidated" }) {
  const { data, loading, error } = useApi(
    () => Promise.all([api.getSegments(ticker, { basis }), api.getSegmentGrowth(ticker, { basis })]),
    [ticker, basis]
  );

  if (loading) return <StatusBanner loading loadingText="Loading segments..." />;
  if (error) return <StatusBanner error={error} />;

  const [segments, growth] = data;

  if (!segments.ok) {
    return <p className="muted">{segments.limitations?.join(" ") || "No reportable segments for this company."}</p>;
  }

  const growthBySegment = Object.fromEntries((growth.rows || []).map((r) => [r.segment, r]));

  return (
    <div>
      <p className="section-note">
        Segment revenue is disclosed in filings; segment margin is not (§12) &mdash; reported as
        unavailable rather than approximated.
      </p>
      <table className="data-table">
        <thead>
          <tr>
            <th>Segment</th>
            <th>Revenue</th>
            <th>Contribution</th>
            <th>YoY growth</th>
            <th>Share of total change</th>
          </tr>
        </thead>
        <tbody>
          {segments.rows.map((row) => {
            const g = growthBySegment[row.segment];
            return (
              <tr key={row.segment}>
                <td>{row.segment}</td>
                <td>{fmt(row.revenue)}</td>
                <td>{row.contribution_pct !== null ? `${fmt(row.contribution_pct)}%` : "—"}</td>
                <td>{g?.growth_pct !== undefined && g.growth_pct !== null ? `${fmt(g.growth_pct)}%` : "—"}</td>
                <td>
                  {g?.share_of_total_change_pct !== undefined && g.share_of_total_change_pct !== null
                    ? `${fmt(g.share_of_total_change_pct)}%`
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!growth.ok && <p className="muted">{growth.limitations?.join(" ")}</p>}
    </div>
  );
}
