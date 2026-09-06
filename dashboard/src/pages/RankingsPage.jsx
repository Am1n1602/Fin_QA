import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";
import { RANKING_CATEGORIES } from "../constants/metrics.js";

const COLUMNS = [
  { key: "rank", label: "Rank", align: "num" },
  { key: "symbol", label: "Company", align: "" },
  { key: "composite_score", label: "Composite", align: "num" },
  ...RANKING_CATEGORIES.map((c) => ({ key: c.key, label: c.label, align: "num", category: true })),
];

function valueFor(ranking, symbol, key) {
  const r = ranking[symbol];
  if (key === "symbol") return symbol;
  if (key === "rank") return r.rank;
  if (key === "composite_score") return r.composite_score;
  return r.category_scores?.[key] ?? null;
}

function makeComparator(ranking, key, dir) {
  return (a, b) => {
    const av = valueFor(ranking, a, key);
    const bv = valueFor(ranking, b, key);
    const aNull = av === null || av === undefined;
    const bNull = bv === null || bv === undefined;
    if (aNull && bNull) return 0;
    if (aNull) return 1; // missing data always sorts last, regardless of direction
    if (bNull) return -1;
    const cmp = typeof av === "string" ? av.localeCompare(bv) : av - bv;
    return dir === "desc" ? -cmp : cmp;
  };
}

function missingTitle(r, categoryKey) {
  const used = r.category_metrics_used?.[categoryKey];
  if (!used) return undefined;
  if (used.missing.length === 0) return `${used.used.length}/${used.used.length} metrics used`;
  return `${used.used.length} used, missing: ${used.missing.join(", ")}`;
}

export default function RankingsPage() {
  const { data: sectorsData } = useApi(() => api.listSectors(), []);
  const [sectorFilter, setSectorFilter] = useState("");
  const [filingType, setFilingType] = useState("consolidated");
  const [sort, setSort] = useState({ key: "rank", dir: "asc" });

  const { data, error, loading } = useApi(
    () => api.getRankings({ sector: sectorFilter || undefined, filingType }),
    [sectorFilter, filingType]
  );

  const sectors = sectorsData ? Object.keys(sectorsData.sectors).sort() : [];

  const sortedSymbols = useMemo(() => {
    if (!data) return [];
    return [...data.symbols].sort(makeComparator(data.ranking, sort.key, sort.dir));
  }, [data, sort]);

  function toggleSort(key) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  function sortIndicator(key) {
    if (sort.key !== key) return null;
    // aria-hidden: the direction is also announced via the header's own
    // aria-sort attribute (see below) -- this glyph is a redundant visual
    // cue only, not an independent source of information for AT users.
    return <span aria-hidden="true">{sort.dir === "asc" ? " ▲" : " ▼"}</span>;
  }

  // WCAG 2.1 SC 4.1.2 (Name, Role, Value): aria-sort tells assistive tech
  // which column a table is currently sorted by and in which direction --
  // there's no way to infer that from DOM order alone once a table is
  // client-side sortable.
  function ariaSortFor(key) {
    if (sort.key !== key) return "none";
    return sort.dir === "asc" ? "ascending" : "descending";
  }

  usePageTitle("Rankings");

  return (
    <div>
      <div className="page-header">
        <h1>Rankings</h1>
        <select value={filingType} onChange={(e) => setFilingType(e.target.value)} aria-label="Filing type">
          <option value="consolidated">Consolidated</option>
          <option value="standalone">Standalone</option>
        </select>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        Composite = equal-weighted percentile average across the 4 categories below. Click a column header to
        sort.
      </p>

      <p className="muted">
        {data ? `${data.symbols.length} compan${data.symbols.length === 1 ? "y" : "ies"} ranked` : " "}
        {sectors.length > 0 && (
          <>
            {" "}
            &middot;{" "}
            <select
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
              aria-label="Filter rankings by sector"
            >
              <option value="">All sectors</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </>
        )}
      </p>

      <StatusBanner loading={loading} error={error} loadingText="Computing rankings...">
        {data && (
          <>
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
                {sortedSymbols.map((symbol) => {
                  const r = data.ranking[symbol];
                  return (
                    <tr key={symbol}>
                      <td className="num">{r.rank ?? <span className="muted">&mdash;</span>}</td>
                      <td>
                        <Link to={`/companies/${symbol}`}>{symbol}</Link>
                      </td>
                      <td className="num">
                        {r.composite_score !== null ? r.composite_score.toFixed(1) : <span className="muted">n/a</span>}
                      </td>
                      {RANKING_CATEGORIES.map((c) => {
                        const score = r.category_scores?.[c.key];
                        return (
                          <td key={c.key} className="num" title={missingTitle(r, c.key)}>
                            {score !== null && score !== undefined ? score.toFixed(1) : <span className="muted">n/a</span>}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="muted" style={{ marginTop: "0.8rem" }}>{data.note}</p>
          </>
        )}
      </StatusBanner>
    </div>
  );
}