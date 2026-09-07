import React from "react";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { RATIO_METRICS, formatValue } from "../../constants/metrics.js";

function numOrDash(value, unit) {
  return value !== null && value !== undefined ? formatValue(value, unit) : <span className="muted">&mdash;</span>;
}

const CRITERION_LABEL = {
  roa_positive: "ROA positive",
  roa_improving: "ROA improving YoY",
  cfo_positive: "Operating cash flow positive",
  leverage_decreasing: "Long-term leverage decreasing",
  liquidity_improving: "Current ratio improving YoY",
  no_dilution: "No share-count dilution",
  asset_turnover_improving: "Asset turnover improving YoY",
  accruals: "CFO/Assets exceeds ROA (accruals)",
};

function MetStatus({ met }) {
  if (met === true) return <span style={{ color: "var(--gain)" }}>MET</span>;
  if (met === false) return <span style={{ color: "var(--loss)" }}>NOT MET</span>;
  return <span className="muted">n/a</span>;
}

function PiotroskiCard({ p }) {
  return (
    <div style={{ marginTop: "0.6rem" }}>
      <h3 style={{ fontSize: "0.95rem" }}>
        Piotroski F-Score: {p.score !== null ? `${p.score}/${p.max_possible_score}` : "n/a"}
      </h3>
      {p.note && <p className="muted">{p.note}</p>}
      {Object.keys(p.criteria).length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Criterion</th>
                <th scope="col">Status</th>
                <th scope="col" className="num">Latest</th>
                <th scope="col" className="num">Prior</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(p.criteria).map(([name, c]) => (
                <tr key={name}>
                  <td>{CRITERION_LABEL[name] || name}</td>
                  <td><MetStatus met={c.met} /></td>
                  <td className="num">{name === "accruals" ? numOrDash(c.cfo_pct, "pct") : numOrDash(c.latest)}</td>
                  <td className="num">{name === "accruals" ? numOrDash(c.roa_pct, "pct") : numOrDash(c.prior)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {Object.keys(p.excluded_criteria).length > 0 && (
        <p className="muted" style={{ marginTop: "0.5rem" }}>
          Excluded (not scored as failing): {Object.entries(p.excluded_criteria).map(([name, reason]) => `${name} (${reason})`).join("; ")}
        </p>
      )}
    </div>
  );
}

function ExcludedSectorBanner({ note }) {
  return (
    <div
      role="note"
      style={{
        marginTop: "0.6rem",
        marginBottom: "0.6rem",
        padding: "0.6rem 0.8rem",
        border: "1px solid var(--border, #444)",
        borderLeft: "3px solid var(--warn, #d9a441)",
        borderRadius: "4px",
      }}
    >
      <strong>Not applicable for this company's filing format.</strong>{" "}
      <span className="muted">{note}</span>{" "}
      <span className="muted">
        See the Capital Adequacy / Asset Quality proxies (Equity/Assets, Credit Cost) in
        Balance-Sheet Strength below instead.
      </span>
    </div>
  );
}

function AltmanCard({ a }) {
  return (
    <div style={{ marginTop: "1.3rem" }}>
      <h3 style={{ fontSize: "0.95rem" }}>Altman Z&Prime;-Score (partial)</h3>
      {a.excluded_sector && <ExcludedSectorBanner note={a.note} />}
      <div className="table-scroll">
        <table className="data-table">
          <tbody>
            <tr>
              <td>X1 -- Working Capital / Assets</td>
              <td className="num">{a.x1_working_capital_to_assets !== null ? formatValue(a.x1_working_capital_to_assets, "pct") : <span className="muted">n/a</span>}</td>
            </tr>
            <tr>
              <td>X3 -- EBIT / Assets</td>
              <td className="num">{a.x3_ebit_to_assets !== null ? formatValue(a.x3_ebit_to_assets, "pct") : <span className="muted">n/a</span>}</td>
            </tr>
            <tr>
              <td>X4 -- Equity / Liabilities</td>
              <td className="num">{a.x4_equity_to_liabilities !== null ? formatValue(a.x4_equity_to_liabilities, "pct") : <span className="muted">n/a</span>}</td>
            </tr>
            <tr>
              <td>partial_z</td>
              <td className="num">{a.partial_z !== null ? a.partial_z : <span className="muted">n/a</span>}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {/* excluded_sector's note is already shown in the banner above --
          avoid printing the same text twice. */}
      {!a.excluded_sector && <p className="muted" style={{ marginTop: "0.5rem" }}>{a.note}</p>}
    </div>
  );
}

function BalanceSheetCard({ b }) {
  return (
    <div style={{ marginTop: "1.3rem" }}>
      <h3 style={{ fontSize: "0.95rem" }}>Balance-Sheet Strength{b.period ? ` (as of ${b.period})` : ""}</h3>
      {b.note && <p className="muted">{b.note}</p>}
      {Object.keys(b.metrics).length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <tbody>
              {Object.entries(b.metrics).map(([key, value]) => (
                <tr key={key}>
                  <td>{RATIO_METRICS[key]?.label || key}</td>
                  <td className="num">{value !== null ? formatValue(value, RATIO_METRICS[key]?.unit) : <span className="muted">no data</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {b.warnings.length > 0 && (
        <p style={{ color: "var(--loss)", marginTop: "0.5rem" }}>{b.warnings.join("; ")}</p>
      )}
    </div>
  );
}

function EarningsConsistencyCard({ e }) {
  return (
    <div style={{ marginTop: "1.3rem" }}>
      <h3 style={{ fontSize: "0.95rem" }}>Earnings Consistency</h3>
      {e.note ? (
        <p className="muted">{e.note}</p>
      ) : (
        <p className="muted">
          Mean NPM {e.mean_npm_pct.toFixed(2)}% across {e.quarters_used} quarters &middot; coefficient of variation{" "}
          {e.coefficient_of_variation}
        </p>
      )}
    </div>
  );
}

export default function HealthSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getHealth(symbol, { filingType }),
    [symbol, filingType]
  );

  return (
    <div className="card">
      <h2>Financial Health</h2>
      <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} financial health...`}>
        {data && (
          <>
            <PiotroskiCard p={data.piotroski} />
            <AltmanCard a={data.altman_z_partial} />
            <BalanceSheetCard b={data.balance_sheet_strength} />
            <EarningsConsistencyCard e={data.earnings_consistency} />
            {data.caveats?.length > 0 && (
              <p className="muted" style={{ marginTop: "1.3rem" }}>{data.caveats.join(" ")}</p>
            )}
          </>
        )}
      </StatusBanner>
    </div>
  );
}