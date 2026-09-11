import React, { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";

const METRICS = [
  { key: "roe", label: "Return on Equity" },
  { key: "roce", label: "Return on Capital Employed" },
  { key: "ebitda_margin", label: "EBITDA Margin" },
  { key: "net_profit_margin", label: "Net Profit Margin" },
  { key: "debt_to_equity", label: "Debt / Equity" },
  { key: "pe", label: "P/E" },
  { key: "revenue", label: "Revenue" },
];

export default function RankingsPage() {
  usePageTitle("Rankings");
  const { data: companiesData } = useApi(() => api.listCompanies(), []);
  const [metric, setMetric] = useState("roe");
  const [selected, setSelected] = useState([]);

  const tickers = selected.length >= 2 ? selected : (companiesData?.members || []).slice(0, 15).map((c) => c.ticker);
  const { data: ranking, loading, error } = useApi(
    // period pinned to FY2026 -- compare_companies defaults to "latest", which for
    // quarterly filers resolves to the latest QUARTER, not the annual period.
    () => (tickers.length >= 2 ? api.getRankings({ metric, tickers, period: "FY2026" }) : Promise.resolve(null)),
    [metric, tickers.join(",")]
  );

  function toggle(ticker) {
    setSelected((prev) => (prev.includes(ticker) ? prev.filter((t) => t !== ticker) : [...prev, ticker]));
  }

  return (
    <div>
      <div className="page-header">
        <h1>Rankings</h1>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        Order companies on one metric or ratio. Defaults to the first 15 NIFTY 50 names; pick
        specific companies below to compare a custom set instead.
      </p>

      <label htmlFor="rank-metric" className="visually-hidden">
        Rank by
      </label>
      <select id="rank-metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
        {METRICS.map((m) => (
          <option key={m.key} value={m.key}>
            {m.label}
          </option>
        ))}
      </select>

      <details className="picker" style={{ marginTop: "0.8rem" }}>
        <summary>Choose companies ({selected.length} selected)</summary>
        <div className="chip-picker">
          {(companiesData?.members || []).map((c) => (
            <label key={c.ticker} className="chip-checkbox">
              <input type="checkbox" checked={selected.includes(c.ticker)} onChange={() => toggle(c.ticker)} />
              {c.ticker}
            </label>
          ))}
        </div>
      </details>

      {loading && <StatusBanner loading loadingText="Ranking..." />}
      {error && <StatusBanner error={error} />}
      {ranking && (
        <table className="data-table" style={{ marginTop: "1rem" }}>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Ticker</th>
              <th>{METRICS.find((m) => m.key === metric)?.label}</th>
            </tr>
          </thead>
          <tbody>
            {ranking.results.map((r) => (
              <tr key={r.ticker}>
                <td>{r.rank}</td>
                <td>
                  <Link to={`/companies/${r.ticker}`}>{r.ticker}</Link>
                </td>
                <td>{r.value !== null ? r.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {ranking?.missing?.length > 0 && (
        <p className="muted">No {metric} available for: {ranking.missing.join(", ")}.</p>
      )}
    </div>
  );
}
