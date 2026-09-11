import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";

const COMPARE_METRICS = [
  { key: "roe", label: "Return on Equity" },
  { key: "ebitda_margin", label: "EBITDA Margin" },
  { key: "debt_to_equity", label: "Debt / Equity" },
  { key: "pe", label: "P/E" },
];

export default function PeersSection({ ticker, basis = "consolidated" }) {
  const [metric, setMetric] = useState("roe");
  const { data: peersData, loading: peersLoading, error: peersError } = useApi(
    () => api.getPeers(ticker, { limit: 10 }),
    [ticker]
  );

  const tickers = peersData ? [ticker, ...peersData.peers.map((p) => p.ticker)] : [];
  const { data: ranking, loading: rankLoading, error: rankError } = useApi(
    // period pinned to FY2026 (matches Ratios/Trends) -- compare_companies defaults to
    // "latest", which for quarterly filers resolves to the latest QUARTER, not the annual
    // period, understating an annual ratio like ROE by roughly 4x.
    () => (tickers.length > 1 ? api.getRankings({ metric, tickers, period: "FY2026", basis }) : Promise.resolve(null)),
    [ticker, metric, peersData, basis]
  );

  if (peersLoading) return <StatusBanner loading loadingText="Loading peers..." />;
  if (peersError) return <StatusBanner error={peersError} />;

  return (
    <div>
      <p className="section-note">
        Same-sector active companies ({peersData.sector || "sector unknown"}), compared on one metric at a time.
      </p>

      <label htmlFor="peer-metric" className="visually-hidden">
        Compare peers by
      </label>
      <select id="peer-metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
        {COMPARE_METRICS.map((m) => (
          <option key={m.key} value={m.key}>
            {m.label}
          </option>
        ))}
      </select>

      {rankLoading && <StatusBanner loading loadingText="Comparing..." />}
      {rankError && <StatusBanner error={rankError} />}
      {ranking && (
        <table className="data-table" style={{ marginTop: "0.8rem" }}>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Ticker</th>
              <th>{COMPARE_METRICS.find((m) => m.key === metric)?.label}</th>
            </tr>
          </thead>
          <tbody>
            {ranking.results.map((r) => (
              <tr key={r.ticker} className={r.ticker === ticker ? "row-highlight" : ""}>
                <td>{r.rank}</td>
                <td>
                  <Link to={`/companies/${r.ticker}`}>{r.ticker}</Link>
                  {r.ticker === ticker && <span className="tag" style={{ marginLeft: "0.4rem" }}>this company</span>}
                </td>
                <td>{r.value !== null ? r.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {ranking?.missing?.length > 0 && (
        <p className="muted">No {metric} for: {ranking.missing.join(", ")}.</p>
      )}
    </div>
  );
}
