import React, { useMemo, useState } from "react";
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

const COLUMNS = [
  { key: "symbol", label: "Company", align: "" },
  { key: "value", label: "Value", align: "num" },
  { key: "rank", label: "Rank", align: "num" },
  { key: "percentile", label: "Percentile", align: "num" },
];

function valueFor(sym, c, key) {
  if (key === "symbol") return sym;
  if (key === "value") return c.status === "ok" ? c.value : null;
  return c[key] ?? null;
}

function makeComparator(companies, key, dir) {
  return ([symA, cA], [symB, cB]) => {
    const av = valueFor(symA, cA, key);
    const bv = valueFor(symB, cB, key);
    const aNull = av === null || av === undefined;
    const bNull = bv === null || bv === undefined;
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
    return dir === "desc" ? -cmp : cmp;
  };
}

function MetricBlock({ metricName, block, focalSymbol }) {
  const meta = RATIO_METRICS[metricName];
  const unit = meta?.unit;
  const [sort, setSort] = useState({ key: null, dir: "asc" });

  const entries = useMemo(() => {
    const list = Object.entries(block.companies);
    if (!sort.key) return list; // original (backend-ranked) order until the user picks a column
    return [...list].sort(makeComparator(block.companies, sort.key, sort.dir));
  }, [block.companies, sort]);

  function toggleSort(key) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  function sortIndicator(key) {
    if (sort.key !== key) return null;
    return <span aria-hidden="true">{sort.dir === "asc" ? " ▲" : " ▼"}</span>;
  }

  function ariaSortFor(key) {
    if (sort.key !== key) return "none";
    return sort.dir === "asc" ? "ascending" : "descending";
  }

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
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key} scope="col" className={col.align} aria-sort={ariaSortFor(col.key)}>
                  <button type="button" className="sort-button" onClick={() => toggleSort(col.key)}>
                    {col.label}
                    {sortIndicator(col.key)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map(([sym, c]) => (
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