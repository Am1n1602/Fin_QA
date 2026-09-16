import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import StatTile from "../../components/StatTile.jsx";

const RATIOS = [
  { key: "roe", label: "Return on Equity" },
  { key: "roce", label: "Return on Capital Employed" },
  { key: "ebitda_margin", label: "EBITDA Margin" },
  { key: "net_profit_margin", label: "Net Profit Margin" },
  { key: "debt_to_equity", label: "Debt / Equity" },
  { key: "current_ratio", label: "Current Ratio" },
];

const VALUATION = [
  { key: "pe", label: "P/E" },
  { key: "pb", label: "P/B" },
  { key: "dividend_yield", label: "Dividend Yield" },
];

export default function RatiosSection({ ticker, period = "FY2026", basis = "consolidated" }) {
  const all = [...RATIOS, ...VALUATION];
  const { data, loading, error } = useApi(
    () => Promise.all(all.map((r) => api.getRatio(ticker, { ratio: r.key, period, basis }))),
    [ticker, period, basis]
  );

  if (loading) return <StatusBanner loading loadingText="Loading ratios..." />;
  if (error) return <StatusBanner error={error} />;

  return (
    <div>
      <p className="section-note">Ratios and valuation multiples, period {period}, {basis} basis.</p>
      <div className="stat-grid">
        {data.map((res, i) => (
          <StatTile
            key={all[i].key}
            label={all[i].label}
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
