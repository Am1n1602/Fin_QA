import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { formatChangeAbsolute, formatGrowthPct } from "../../constants/metrics.js";

const GROWTH_FIELDS = [
  { key: "revenue", label: "Revenue" },
  { key: "net_profit", label: "Net Profit" },
  { key: "pbt", label: "Profit Before Tax" },
  { key: "total_expenses", label: "Total Expenses" },
];


function GrowthCell({ entry, field }) {
  const pct = entry[`${field}_growth_pct`];
  const abs = entry[`${field}_change_absolute`];
  const note = entry[`${field}_growth_note`];
  if (pct !== null && pct !== undefined) {
    return (
      <span style={{ color: pct >= 0 ? "var(--gain)" : "var(--loss)" }}>{formatGrowthPct(pct)}</span>
    );
  }
  if (abs !== null && abs !== undefined) {
    return (
      <span title={note}>
        {formatChangeAbsolute(abs)} <span className="muted">(abs.)</span>
      </span>
    );
  }
  return <span className="muted">no data</span>;
}

function TrendsTable({ rows }) {
  return (
    <table className="data-table">
      <thead>
        <tr>
          <th scope="col">Period</th>
          {GROWTH_FIELDS.map((f) => (
            <th key={f.key} scope="col" className="num">{f.label}</th>
          ))}
          <th scope="col" className="num">Operating Leverage</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((entry, i) => (
          <tr key={i}>
            <td>
              {entry.from_period} &rarr; {entry.to_period}
            </td>
            {GROWTH_FIELDS.map((f) => (
              <td key={f.key} className="num">
                <GrowthCell entry={entry} field={f.key} />
              </td>
            ))}
            <td className="num">
              {entry.operating_leverage_signal !== null && entry.operating_leverage_signal !== undefined ? (
                `${entry.operating_leverage_signal >= 0 ? "+" : ""}${entry.operating_leverage_signal.toFixed(2)}pp`
              ) : (
                <span className="muted">n/a</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function TrendsSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getTrends(symbol, { filingType }),
    [symbol, filingType]
  );

  return (
    <div className="card">
      <h2>Trends</h2>
      <p className="byline" style={{ marginTop: 0 }}>
        Quarter-over-quarter and year-over-year growth, computed from real reporting periods only.
      </p>
      <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} trends...`}>
        {data && (
          <>
            <h3 style={{ fontSize: "0.95rem", marginTop: "0.6rem" }}>Annual Year-over-Year</h3>
            {data.annual_yoy ? (
              <>
                <p className="muted" style={{ margin: "0 0 0.4rem" }}>
                  {data.annual_yoy.prior_period_end} &rarr; {data.annual_yoy.latest_period_end}
                </p>
                <TrendsTable rows={[data.annual_yoy]} />
                {data.annual_yoy.eps_basic_growth_pct !== undefined && (
                  <p className="muted" style={{ marginTop: "0.6rem" }}>
                    EPS (Basic) growth: <GrowthCell entry={data.annual_yoy} field="eps_basic" />
                  </p>
                )}
              </>
            ) : (
              <p className="muted">Fewer than 2 real annual periods on file yet -- YoY growth not available.</p>
            )}

            <h3 style={{ fontSize: "0.95rem", marginTop: "1.4rem" }}>Quarter-over-Quarter</h3>
            {data.trends && data.trends.length > 0 ? (
              <TrendsTable rows={data.trends} />
            ) : (
              <p className="muted">No consecutive single-quarter periods on file yet.</p>
            )}
          </>
        )}
      </StatusBanner>
    </div>
  );
}