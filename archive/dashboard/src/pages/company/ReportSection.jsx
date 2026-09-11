import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { formatValue } from "../../constants/metrics.js";

const VALUATION_FIELDS = [
  { key: "pe_ratio", label: "P/E Ratio", unit: "x" },
  { key: "pb_ratio", label: "P/B Ratio", unit: "x" },
  { key: "earnings_yield_pct", label: "Earnings Yield", unit: "pct" },
  { key: "ev_to_sales", label: "EV / Sales", unit: "x" },
  { key: "dividend_yield_pct", label: "Dividend Yield", unit: "pct" },
  { key: "enterprise_value", label: "Enterprise Value", unit: "currency" },
];

function FlagsList({ flags }) {
  const strengths = flags.filter((f) => f.type === "strength");
  const risks = flags.filter((f) => f.type === "risk");
  return (
    <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", marginTop: "0.6rem" }}>
      <div style={{ flex: "1 1 260px" }}>
        <h4 style={{ fontSize: "0.9rem", color: "var(--gain)" }}>Strengths ({strengths.length})</h4>
        {strengths.length === 0 ? (
          <p className="muted">None flagged.</p>
        ) : (
          <ul style={{ paddingLeft: "1.1rem", margin: 0 }}>
            {strengths.map((f, i) => (
              <li key={i} style={{ marginBottom: "0.4rem" }}>
                <span className="muted">({f.source})</span> {f.detail}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div style={{ flex: "1 1 260px" }}>
        <h4 style={{ fontSize: "0.9rem", color: "var(--loss)" }}>Risks ({risks.length})</h4>
        {risks.length === 0 ? (
          <p className="muted">None flagged.</p>
        ) : (
          <ul style={{ paddingLeft: "1.1rem", margin: 0 }}>
            {risks.map((f, i) => (
              <li key={i} style={{ marginBottom: "0.4rem" }}>
                <span className="muted">({f.source})</span> {f.detail}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function ReportSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getReport(symbol, { filingType }),
    [symbol, filingType]
  );

  return (
    <div className="card">
      <h2>Research Report</h2>
      <StatusBanner loading={loading} error={error} loadingText={`Compiling ${symbol} report...`}>
        {data && (
          <>
            <p className="byline" style={{ marginTop: 0 }}>
              Generated {data.generated_at} &middot; peers: {data.peer_symbols.join(", ") || "none"}
            </p>
            {data.peer_selection_warning && <p className="muted">{data.peer_selection_warning}</p>}

            <h3 style={{ fontSize: "0.95rem", marginTop: "0.9rem" }}>Valuation Snapshot</h3>
            <div className="table-scroll">
              <table className="data-table">
                <tbody>
                  {VALUATION_FIELDS.map((f) => (
                    <tr key={f.key}>
                      <td>{f.label}</td>
                      <td className="num">
                        {data.valuation[f.key] !== null && data.valuation[f.key] !== undefined
                          ? formatValue(data.valuation[f.key], f.unit)
                          : <span className="muted">no data</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.valuation.data_quality_warnings.length > 0 && (
              <p style={{ color: "var(--loss)", marginTop: "0.5rem" }}>
                {data.valuation.data_quality_warnings.join(" ")}
              </p>
            )}

            <h3 style={{ fontSize: "0.95rem", marginTop: "1.3rem" }}>Flags</h3>
            <FlagsList flags={data.flags} />

            <h3 style={{ fontSize: "0.95rem", marginTop: "1.3rem" }}>Data Sources</h3>
            <p className="muted">{data.data_sources.canonical_files.join(", ") || "none on file"}</p>

            <h3 style={{ fontSize: "0.95rem", marginTop: "1.3rem" }}>Caveats</h3>
            <ul style={{ paddingLeft: "1.1rem" }}>
              {data.caveats.map((c, i) => (
                <li key={i} className="muted" style={{ marginBottom: "0.4rem" }}>{c}</li>
              ))}
            </ul>
          </>
        )}
      </StatusBanner>
    </div>
  );
}