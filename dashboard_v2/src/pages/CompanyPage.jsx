import React, { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";
import FinancialsSection from "./company/FinancialsSection.jsx";
import RatiosSection from "./company/RatiosSection.jsx";
import TrendsSection from "./company/TrendsSection.jsx";
import SegmentsSection from "./company/SegmentsSection.jsx";
import PeersSection from "./company/PeersSection.jsx";

const TABS = [
  { key: "financials", label: "Financials", Component: FinancialsSection },
  { key: "ratios", label: "Ratios", Component: RatiosSection },
  { key: "trends", label: "Trends", Component: TrendsSection },
  { key: "segments", label: "Segments", Component: SegmentsSection },
  { key: "peers", label: "Peer Comparison", Component: PeersSection },
];

export default function CompanyPage() {
  const { ticker } = useParams();
  const { data: company, loading, error } = useApi(() => api.getCompany(ticker), [ticker]);
  const [tab, setTab] = useState("financials");
  // Consolidated is the right default for most companies, but a standalone-only filer
  // (e.g. an insurer like SBILIFE/HDFCLIFE) reports nothing under "consolidated" at all --
  // the number exists, just under the other basis, so this is a manual toggle rather than
  // an automatic fallback: silently substituting one for the other would conflate two
  // genuinely different views of the same company's financials.
  const [basis, setBasis] = useState("consolidated");
  usePageTitle(company ? `${company.ticker} — ${company.name}` : ticker);

  if (loading) return <StatusBanner loading loadingText={`Loading ${ticker}...`} />;
  if (error) return <StatusBanner error={error} />;
  if (!company) return null;

  const ActiveSection = TABS.find((t) => t.key === tab)?.Component;

  return (
    <div>
      <div className="page-header">
        <h1>
          {company.name} <span className="muted">({company.ticker})</span>
        </h1>
        <Link to={`/research/${company.ticker}`} className="tag">
          Full research report &rarr;
        </Link>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        {company.sector || "Sector unknown"}
        {company.industry ? ` · ${company.industry}` : ""}
        {company.isin ? ` · ${company.isin}` : ""}
        {!company.active && " · inactive"}
      </p>

      <div className="tab-row" role="tablist" aria-label="Company sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            className={"tab-button" + (tab === t.key ? " tab-button-active" : "")}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        <div className="basis-toggle" role="radiogroup" aria-label="Reporting basis">
          {["consolidated", "standalone"].map((b) => (
            <button
              key={b}
              type="button"
              role="radio"
              aria-checked={basis === b}
              className={"basis-toggle-option" + (basis === b ? " basis-toggle-option-active" : "")}
              onClick={() => setBasis(b)}
              title={
                b === "standalone"
                  ? "Standalone-only filers (e.g. insurers) report nothing under consolidated"
                  : "Group-level figures (default for most companies)"
              }
            >
              {b === "consolidated" ? "Consolidated" : "Standalone"}
            </button>
          ))}
        </div>
      </div>

      <div role="tabpanel" className="tab-panel">
        {ActiveSection && <ActiveSection ticker={company.ticker} basis={basis} />}
      </div>
    </div>
  );
}
