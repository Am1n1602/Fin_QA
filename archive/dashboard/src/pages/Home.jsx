import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";

function HealthPill({ health, error }) {
  if (error) return <span className="pill pill-down">OFFLINE</span>;
  if (!health) return <span className="pill pill-pending">CONNECTING</span>;
  if (!health.analysis_engine_ready) return <span className="pill pill-pending">STARTING</span>;
  return (
    <span className="pill pill-up">LIVE{health.rag_engine_ready ? "" : " · RAG WARMING"}</span>
  );
}

export default function Home() {
  usePageTitle("Market Overview");
  const { data: health, error: healthError } = useApi(() => api.health(), []);
  const { data: companies, error: companiesError, loading: companiesLoading } = useApi(
    () => api.listCompanies(),
    []
  );
  const [sectorFilter, setSectorFilter] = useState("");

  const sectors = useMemo(() => {
    if (!companies) return [];
    return [...new Set(companies.map((c) => c.sector || "UNCLASSIFIED"))].sort();
  }, [companies]);

  const visibleCompanies = useMemo(() => {
    if (!companies) return [];
    if (!sectorFilter) return companies;
    return companies.filter((c) => (c.sector || "UNCLASSIFIED") === sectorFilter);
  }, [companies, sectorFilter]);

  return (
    <div>
      <div className="page-header">
        <h1>Market Overview</h1>
        <HealthPill health={health} error={healthError} />
      </div>
      <p className="byline">Compiled from NSE/BSE filings, normalized through the Fin_QA calculation engine.</p>

      <p className="muted">
        {companies ? `${companies.length} companies on file` : " "}
        {sectors.length > 0 && (
          <>
            {" "}
            across {sectors.length} sectors.{" "}
            <select
              value={sectorFilter}
              onChange={(e) => setSectorFilter(e.target.value)}
              aria-label="Filter companies by sector"
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

      <StatusBanner loading={companiesLoading} error={companiesError} loadingText="Retrieving company register...">
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Symbol</th>
                <th scope="col">Company</th>
                <th scope="col">Sector</th>
                <th scope="col" className="num">BSE Scrip</th>
              </tr>
            </thead>
            <tbody>
              {visibleCompanies.map((c) => (
                <tr key={c.symbol}>
                  <td>
                    <Link to={`/companies/${c.symbol}`}>{c.symbol}</Link>
                  </td>
                  <td>{c.name}</td>
                  <td>
                    {c.sector ? <span className="tag">{c.sector}</span> : <span className="muted">unclassified</span>}
                  </td>
                  <td className="num">{c.bse_scrip || <span className="muted">&mdash;</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </StatusBanner>
    </div>
  );
}