import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";

export default function Home() {
  usePageTitle("Overview");
  const navigate = useNavigate();
  const { data: health, loading, error } = useApi(() => api.health(), []);
  const [ticker, setTicker] = useState("");

  function goToCompany(e) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (t) navigate(`/companies/${t}`);
  }

  return (
    <div>
      <div className="page-header">
        <h1>Fin&middot;QA v2</h1>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        A financial research engine: deterministic numbers from the Financial Engine,
        evidence from structured data and filings, reasoning from an LLM &mdash; and every
        conclusion checked against its evidence before it reaches you.
      </p>

      <form onSubmit={goToCompany} className="home-search" role="search">
        <label htmlFor="ticker-search" className="visually-hidden">
          Jump to a company by ticker
        </label>
        <input
          id="ticker-search"
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="Jump to a company, e.g. TCS"
        />
        <button type="submit">Go</button>
      </form>

      <div className="home-shortcuts">
        {/* React Router <Link>, not a plain <a> -- a real anchor tag forces a full
            browser navigation to that path, which (a) throws away SPA state
            unnecessarily and (b) 404s on a static host with no server-side route for
            it (only index.html gets rewritten there; see render.yaml). */}
        <Link className="card card-link" to="/companies">
          <h2>Companies</h2>
          <p>Browse the NIFTY 50 universe, sector, and profile.</p>
        </Link>
        <Link className="card card-link" to="/rankings">
          <h2>Rankings</h2>
          <p>Order companies by any metric or ratio.</p>
        </Link>
        <Link className="card card-link" to="/research">
          <h2>Research</h2>
          <p>A full evidence-grounded overview of one company.</p>
        </Link>
        <Link className="card card-link" to="/qa">
          <h2>Financial QA</h2>
          <p>Ask a question; every claim comes with its own evidence trail.</p>
        </Link>
      </div>

      <section className="card" style={{ marginTop: "1.5rem" }} aria-label="System status">
        <h2 style={{ marginTop: 0, fontSize: "0.95rem" }}>System status</h2>
        {loading && <StatusBanner loading loadingText="Checking..." />}
        {error && <StatusBanner error={error} />}
        {health && (
          <ul className="status-list">
            <li>Database: {health.db_ready ? "ready" : "starting"}</li>
            <li>Financial Engine: {health.engine_ready ? "ready" : "starting"}</li>
            <li>
              Retrieval:{" "}
              {health.retriever_modes?.length ? health.retriever_modes.join(", ") : "unavailable"}
            </li>
            <li>
              LLM provider: {health.llm_provider === "null" ? "none (deterministic answers only)" : health.llm_provider}
            </li>
          </ul>
        )}
      </section>
    </div>
  );
}
