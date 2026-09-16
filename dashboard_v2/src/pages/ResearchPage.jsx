import React, { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";
import EvidenceAnswer from "../components/EvidenceClaims.jsx";

export default function ResearchPage() {
  const { ticker } = useParams();
  const navigate = useNavigate();
  usePageTitle(ticker ? `Research — ${ticker}` : "Research");
  const { data: companies } = useApi(() => api.listCompanies(), []);
  const [useLlm, setUseLlm] = useState(true);

  const { data: report, loading, error } = useApi(
    () => (ticker ? api.getResearch(ticker, { useLlm }) : Promise.resolve(null)),
    [ticker, useLlm]
  );

  return (
    <div>
      <div className="page-header">
        <h1>Research</h1>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        A full evidence-grounded overview: planner &rarr; Financial Engine &rarr; hybrid
        retrieval &rarr; reasoning &rarr; verification. Every claim below can be expanded to
        see exactly where it came from.
      </p>

      <div className="filter-row">
        <label htmlFor="research-ticker" className="visually-hidden">
          Company
        </label>
        <select
          id="research-ticker"
          value={ticker || ""}
          onChange={(e) => navigate(e.target.value ? `/research/${e.target.value}` : "/research")}
        >
          <option value="">Choose a company...</option>
          {(companies?.members || []).map((c) => (
            <option key={c.ticker} value={c.ticker}>
              {c.ticker} — {c.name}
            </option>
          ))}
        </select>
        <label className="checkbox-inline">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Use LLM synthesis
        </label>
      </div>

      {!ticker && <p className="muted">Choose a company above to generate its research report.</p>}
      {loading && <StatusBanner loading loadingText={`Building the research report for ${ticker}...`} />}
      {error && <StatusBanner error={error} />}
      {report && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <EvidenceAnswer result={report} contextLabel={ticker} />
        </div>
      )}
    </div>
  );
}
