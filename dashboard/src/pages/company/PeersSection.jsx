import React from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { RATIO_METRICS, formatValue } from "../../constants/metrics.js";

const DIRECTION_LABEL = {
  higher: "higher is better",
  lower: "lower is better",
  neutral: "neutral -- not auto-judged",
};

function MetricBlock({ metricName, block, focalSymbol }) {
  const meta = RATIO_METRICS[metricName];
  const unit = meta?.unit;
  return (
    <div style={{ marginTop: "1.3rem" }}>
      <h3 style={{ fontSize: "0.95rem", marginBottom: "0.15rem" }}>{meta?.label || metricName}</h3>
      <p className="muted" style={{ margin: "0 0 0.5rem" }}>
        {DIRECTION_LABEL[block.direction] || block.direction}
        {block.leader && (
          <>
            {" "}
            &middot; leader: <strong>{block.leader}</strong> ({formatValue(block.leader_value, unit)})
          </>
        )}
        {block.sector_median !== null && block.sector_median !== undefined && (
          <> &middot; peer median {formatValue(block.sector_median, unit)}</>
        )}
      </p>
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Company</th>
            <th scope="col" className="num">Value</th>
            <th scope="col" className="num">Rank</th>
            <th scope="col" className="num">Percentile</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(block.companies).map(([sym, c]) => (
            <tr key={sym} style={sym === focalSymbol ? { fontWeight: 600 } : undefined}>
              <td>
                <Link to={`/companies/${sym}`}>{sym}</Link>
                {sym === focalSymbol && <span className="visually-hidden"> (this company)</span>}
              </td>
              <td className="num">
                {c.status === "ok" ? formatValue(c.value, unit) : <span className="muted">no data</span>}
              </td>
              <td className="num">{c.rank ?? <span className="muted">&mdash;</span>}</td>
              <td className="num">{c.percentile !== null && c.percentile !== undefined ? `${c.percentile}%` : <span className="muted">&mdash;</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PeersSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getPeers(symbol, { filingType }),
    [symbol, filingType]
  );

  return (
    <div className="card">
      <h2>Peer Comparison</h2>
      <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} peer comparison...`}>
        {data && (
          <>
            <p className="byline" style={{ marginTop: 0 }}>
              {data.sector ? `Sector: ${data.sector}` : "Sector not classified"} &middot; {data.peers.length} peer(s)
            </p>
            {data.warning && <p className="muted">{data.warning}</p>}
            {Object.entries(data.comparison).map(([metricName, block]) => (
              <MetricBlock key={metricName} metricName={metricName} block={block} focalSymbol={data.symbol} />
            ))}
          </>
        )}
      </StatusBanner>
    </div>
  );
}