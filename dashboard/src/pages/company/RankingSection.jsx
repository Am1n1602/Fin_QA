import React from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import { useApi } from "../../api/useApi.js";
import StatusBanner from "../../components/StatusBanner.jsx";
import { RANKING_CATEGORIES } from "../../constants/metrics.js";

function ScoreCell({ score }) {
  if (score === null || score === undefined) return <span className="muted">n/a</span>;
  return `${score.toFixed(1)}`;
}

export default function RankingSection({ symbol, filingType }) {
  const { data, error, loading } = useApi(
    () => api.getCompanyRanking(symbol, { filingType }),
    [symbol, filingType]
  );

  const focal = data?.ranking?.[symbol];

  return (
    <div className="card">
      <h2>Ranking</h2>
      <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} ranking...`}>
        {data && (
          <>
            <p className="byline" style={{ marginTop: 0 }}>
              {data.sector ? `Sector: ${data.sector}` : "Sector not classified"} &middot; {data.symbols.length} compan
              {data.symbols.length === 1 ? "y" : "ies"} ranked
            </p>
            {data.warning && <p className="muted">{data.warning}</p>}

            {focal && (
              <p className="muted">
                {symbol}: composite <strong>{focal.composite_score !== null ? focal.composite_score.toFixed(1) : "n/a"}</strong>
                {focal.rank !== null ? <> &middot; rank #{focal.rank} of {data.symbols.length}</> : null}
              </p>
            )}

            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col" className="num">Rank</th>
                  <th scope="col">Company</th>
                  <th scope="col" className="num">Composite</th>
                  {RANKING_CATEGORIES.map((c) => (
                    <th key={c.key} scope="col" className="num">{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.ordered_symbols.map((sym) => {
                  const r = data.ranking[sym];
                  return (
                    <tr key={sym} style={sym === symbol ? { fontWeight: 600 } : undefined}>
                      <td className="num">{r.rank ?? <span className="muted">&mdash;</span>}</td>
                      <td>
                        <Link to={`/companies/${sym}`}>{sym}</Link>
                        {sym === symbol && <span className="visually-hidden"> (this company)</span>}
                      </td>
                      <td className="num">{r.composite_score !== null ? r.composite_score.toFixed(1) : <span className="muted">n/a</span>}</td>
                      {RANKING_CATEGORIES.map((c) => (
                        <td key={c.key} className="num">
                          <ScoreCell score={r.category_scores?.[c.key]} />
                        </td>
                      ))}
                    </tr>
                  );
                })}
                {data.symbols
                  .filter((sym) => !data.ordered_symbols.includes(sym))
                  .map((sym) => (
                    <tr key={sym} className="muted">
                      <td className="num">&mdash;</td>
                      <td>
                        <Link to={`/companies/${sym}`}>{sym}</Link>
                      </td>
                      <td className="num" colSpan={1 + RANKING_CATEGORIES.length}>
                        no scoreable data
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <p className="muted" style={{ marginTop: "0.8rem" }}>{data.note}</p>
          </>
        )}
      </StatusBanner>
    </div>
  );
}