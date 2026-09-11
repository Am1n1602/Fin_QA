import React, { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";
import FinancialsSection from "./company/FinancialsSection.jsx";
import RatiosSection from "./company/RatiosSection.jsx";
import TrendsSection from "./company/TrendsSection.jsx";
import PeersSection from "./company/PeersSection.jsx";
import RankingSection from "./company/RankingSection.jsx";
import HealthSection from "./company/HealthSection.jsx";
import ReportSection from "./company/ReportSection.jsx";

const ACRONYMS = new Set(["pe", "pb", "roe", "roce", "npm", "ebitda", "eps", "cfo", "pat"]);

function formatMetricLabel(key) {
  const words = key.split("_").filter((w) => w !== "pct");
  const label = words
    .map((w) => (ACRONYMS.has(w) ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
  return key.endsWith("_pct") ? `${label} %` : label;
}

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "financials", label: "Financials" },
  { key: "ratios", label: "Ratios" },
  { key: "trends", label: "Trends" },
  { key: "peers", label: "Peers" },
  { key: "ranking", label: "Ranking" },
  { key: "health", label: "Health" },
  { key: "report", label: "Report" },
];

function OverviewTab({ symbol, filingType }) {
  const { data, error, loading } = useApi(() => api.getCompany(symbol, { filingType }), [symbol, filingType]);

  return (
    <StatusBanner loading={loading} error={error} loadingText={`Retrieving ${symbol} overview...`}>
      {data && (
        <div className="card">
          <h2>{data.name}</h2>
          <p className="muted">
            {data.sector ? <span className="tag">{data.sector}</span> : "Unclassified sector"} &middot; BSE{" "}
            {data.bse_scrip || "n/a"}
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Metric</th>
                  <th scope="col" className="num">Latest Value</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.snapshot).map(([metric, point]) => (
                  <tr key={metric}>
                    <td>{formatMetricLabel(metric)}</td>
                    <td className="num">
                      {point ? (
                        <>
                          {point.value}
                          <span className="muted"> ({point.period})</span>
                        </>
                      ) : (
                        <span className="muted">no data</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="byline" style={{ marginTop: "1.1rem", marginBottom: 0 }}>
            Use the tabs above for the full financials, ratios, trends, peer comparison, ranking, financial
            health and research report.
          </p>
        </div>
      )}
    </StatusBanner>
  );
}

export default function CompanyPage() {
  const { symbol } = useParams();
  const [activeTab, setActiveTab] = useState("overview");
  const [filingType, setFilingType] = useState("consolidated");
  const tabRefs = useRef({});

  usePageTitle(symbol);

  function focusTab(key) {
    setActiveTab(key);
    tabRefs.current[key]?.focus();
  }

  function handleTabKeyDown(e, index) {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    let nextIndex = index;
    if (e.key === "ArrowRight") nextIndex = (index + 1) % TABS.length;
    else if (e.key === "ArrowLeft") nextIndex = (index - 1 + TABS.length) % TABS.length;
    else if (e.key === "Home") nextIndex = 0;
    else if (e.key === "End") nextIndex = TABS.length - 1;
    focusTab(TABS[nextIndex].key);
  }

  return (
    <div>
      <div className="page-header">
        <h1>{symbol}</h1>
        <select
          value={filingType}
          onChange={(e) => setFilingType(e.target.value)}
          aria-label="Filing type"
        >
          <option value="consolidated">Consolidated</option>
          <option value="standalone">Standalone</option>
        </select>
      </div>

      <div className="section-tabs" role="tablist" aria-label="Company data sections">
        {TABS.map((tab, index) => (
          <button
            key={tab.key}
            ref={(el) => (tabRefs.current[tab.key] = el)}
            type="button"
            role="tab"
            id={`tab-${tab.key}`}
            aria-selected={activeTab === tab.key}
            aria-controls={`panel-${tab.key}`}
            tabIndex={activeTab === tab.key ? 0 : -1}
            className={"section-tab" + (activeTab === tab.key ? " section-tab-active" : "")}
            onClick={() => setActiveTab(tab.key)}
            onKeyDown={(e) => handleTabKeyDown(e, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        role="tabpanel"
        id={`panel-${activeTab}`}
        aria-labelledby={`tab-${activeTab}`}
        tabIndex={0}
      >
        {activeTab === "overview" && <OverviewTab symbol={symbol} filingType={filingType} />}
        {activeTab === "financials" && <FinancialsSection symbol={symbol} filingType={filingType} />}
        {activeTab === "ratios" && <RatiosSection symbol={symbol} filingType={filingType} />}
        {activeTab === "trends" && <TrendsSection symbol={symbol} filingType={filingType} />}
        {activeTab === "peers" && <PeersSection symbol={symbol} filingType={filingType} />}
        {activeTab === "ranking" && <RankingSection symbol={symbol} filingType={filingType} />}
        {activeTab === "health" && <HealthSection symbol={symbol} filingType={filingType} />}
        {activeTab === "report" && <ReportSection symbol={symbol} filingType={filingType} />}
      </div>
    </div>
  );
}