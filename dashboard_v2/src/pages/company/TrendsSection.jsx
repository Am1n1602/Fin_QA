import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import StatTile from "../../components/StatTile.jsx";

const GROWTH_METRICS = [
  { key: "revenue", label: "Revenue Growth (YoY)" },
  { key: "net_profit", label: "Net Profit Growth (YoY)" },
];

export default function TrendsSection({ ticker, period = "FY2026", basis = "consolidated" }) {
  const { data, loading, error } = useApi(
    () =>
      Promise.all([
        ...GROWTH_METRICS.map((m) => api.getGrowth(ticker, { metric: m.key, kind: "yoy", basis })),
        api.getCagr(ticker, { metric: "revenue", basis }),
        // must match the Ratios tab's period -- decompose defaults to "latest", which for a
        // company with quarterly filings resolves to the latest QUARTER, not the latest
        // annual period, giving an unannualised (and much smaller) ROE breakdown otherwise.
        api.decompose(ticker, { metric: "roe", period, basis }),
      ]),
    [ticker, period, basis]
  );

  if (loading) return <StatusBanner loading loadingText="Loading trends..." />;
  if (error) return <StatusBanner error={error} />;

  const [revenueGrowth, netProfitGrowth, revenueCagr, dupont] = data;
  const factors = dupont?.components?.components || {};

  return (
    <div>
      <p className="section-note">
        Year-over-year growth, CAGR, and the DuPont decomposition of ROE (net margin &times;
        asset turnover &times; equity multiplier).
      </p>
      <div className="stat-grid">
        <StatTile label={GROWTH_METRICS[0].label} value={revenueGrowth.value} unit={revenueGrowth.unit}
                 period={revenueGrowth.period} limitations={revenueGrowth.limitations} />
        <StatTile label={GROWTH_METRICS[1].label} value={netProfitGrowth.value} unit={netProfitGrowth.unit}
                 period={netProfitGrowth.period} limitations={netProfitGrowth.limitations} />
        <StatTile label="Revenue CAGR" value={revenueCagr.value} unit={revenueCagr.unit}
                 period={revenueCagr.period} limitations={revenueCagr.limitations} />
      </div>

      {Object.keys(factors).length > 0 && (
        <>
          <h3 className="subsection-title">DuPont decomposition — ROE {period}</h3>
          <table className="data-table">
            <thead>
              <tr>
                <th>Factor</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(factors).map(([k, v]) => (
                <tr key={k}>
                  <td>{k.replace(/_/g, " ")}</td>
                  <td>{typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            Reconstructed ROE {dupont.components.reconstructed_roe_pct?.toFixed(2)}% vs. actual{" "}
            {dupont.components.actual_roe_pct?.toFixed(2)}%
            {dupont.components.reconciles ? " (reconciles)." : " (does not reconcile)."}
          </p>
        </>
      )}
      {dupont?.limitations?.length > 0 && <p className="muted">{dupont.limitations.join(" ")}</p>}
    </div>
  );
}
