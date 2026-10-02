import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import StatTile from "../../components/StatTile.jsx";

const METRICS = [
  { key: "revenue", label: "Revenue" },
  { key: "net_profit", label: "Net Profit" },
  { key: "total_assets", label: "Total Assets" },
  { key: "total_equity", label: "Total Equity" },
  { key: "ebitda", label: "EBITDA" },
  { key: "cash_and_equivalents", label: "Cash & Equivalents" },
];

export default function FinancialsSection({ ticker, basis = "consolidated" }) {
  // No `period`: the API defaults to the latest annual period; each tile shows the one it used.
  const { data, loading, error } = useApi(
    () => Promise.all(METRICS.map((m) => api.getFinancial(ticker, { metric: m.key, basis }))),
    [ticker, basis]
  );

  if (loading) return <StatusBanner loading loadingText="Loading financials..." />;
  if (error) return <StatusBanner error={error} />;

  return (
    <div>
      <p className="section-note">
        Raw or derived figures from the Financial Engine, latest annual period, {basis} basis.
      </p>
      <div className="stat-grid">
        {data.map((res, i) => (
          <StatTile
            key={METRICS[i].key}
            label={METRICS[i].label}
            value={res.value}
            unit={res.unit}
            period={res.period}
            limitations={res.limitations}
          />
        ))}
      </div>
    </div>
  );
}
