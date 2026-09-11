import React, { useMemo, useState } from "react";
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

const COLUMNS = [
  { key: "period", label: "Period", align: "" },
  ...GROWTH_FIELDS.map((f) => ({ key: f.key, label: f.label, align: "num" })),
  { key: "operating_leverage_signal", label: "Operating Leverage", align: "num" },
];

function valueFor(entry, key) {
  if (key === "period") return entry.to_period || entry.from_period || null;
  if (key === "operating_leverage_signal") {
    const v = entry.operating_leverage_signal;
    return v === null || v === undefined ? null : v;
  }
  const pct = entry[`${key}_growth_pct`];
  if (pct !== null && pct !== undefined) return pct;
  const abs = entry[`${key}_change_absolute`];
  return abs === null || abs === undefined ? null : abs;
}

function makeComparator(key, dir) {
  return (a, b) => {
    const av = valueFor(a, key);
    const bv = valueFor(b, key);
    const aNull = av === null || av === undefined;
    const bNull = bv === null || bv === undefined;
    if (aNull && bNull) return 0;
    if (aNull) return 1;
    if (bNull) return -1;
    const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
    return dir === "desc" ? -cmp : cmp;
  };
}

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

// A table of trend rows (Annual YoY has just one; Quarter-over-Quarter
// usually has several) -- each own its own sort state, since sorting the
// multi-row QoQ table shouldn't do anything to the single-row YoY one.
function TrendsTable({ rows }) {
  const [sort, setSort] = useState({ key: null, dir: "asc" });

  const sortedRows = useMemo(() => {
    if (!sort.key) return rows; // original (chronological, as returned by the API) order
    return [...rows].sort(makeComparator(sort.key, sort.dir));
  }, [rows, sort]);

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
          {sortedRows.map((entry, i) => (
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
    </div>
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