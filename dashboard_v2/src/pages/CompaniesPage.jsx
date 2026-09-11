import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";

export default function CompaniesPage() {
  usePageTitle("Companies");
  const { data, loading, error } = useApi(() => api.listCompanies(), []);
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("");

  const members = data?.members || [];
  const sectors = useMemo(
    () => [...new Set(members.map((c) => c.sector).filter(Boolean))].sort(),
    [members]
  );
  const filtered = members.filter((c) => {
    const q = query.trim().toLowerCase();
    const matchesQuery = !q || c.ticker.toLowerCase().includes(q) || c.name.toLowerCase().includes(q);
    const matchesSector = !sector || c.sector === sector;
    return matchesQuery && matchesSector;
  });

  return (
    <div>
      <div className="page-header">
        <h1>Companies</h1>
        <span className="muted">{data?.index || "NIFTY 50"} &middot; {data?.count ?? "…"} members</span>
      </div>

      <div className="filter-row">
        <label className="visually-hidden" htmlFor="company-search">
          Search companies
        </label>
        <input
          id="company-search"
          type="text"
          placeholder="Search by ticker or name"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <label className="visually-hidden" htmlFor="sector-filter">
          Filter by sector
        </label>
        <select id="sector-filter" value={sector} onChange={(e) => setSector(e.target.value)}>
          <option value="">All sectors</option>
          {sectors.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {loading && <StatusBanner loading loadingText="Loading companies..." />}
      {error && <StatusBanner error={error} />}

      {!loading && !error && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Name</th>
              <th>Sector</th>
              <th>Industry</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr key={c.ticker}>
                <td>
                  <Link to={`/companies/${c.ticker}`}>{c.ticker}</Link>
                </td>
                <td>{c.name}</td>
                <td>{c.sector || "—"}</td>
                <td>{c.industry || "—"}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No companies match this filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
