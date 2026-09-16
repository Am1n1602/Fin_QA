import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";
import { metricLabel } from "../constants/metrics.js";

const INTENT_LABELS = {
  numeric_fact: "Numeric Fact",
  trend: "Trend",
  comparison: "Comparison",
  ranking: "Ranking",
  financial_health: "Financial Health",
  report: "Report",
  narrative: "Narrative (RAG)",
  complex: "Complex",
  unknown: "Unclassified",
};

const EXAMPLE_QUESTIONS = [
  "What is TCS's P/E ratio?",
  "Compare ROE for HDFC Bank and ICICI Bank",
  "Rank the IT services companies by financial health",
  "Why did Infosys's margins change recently?",
];

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function SourceItem({ source }) {
  if (source.type === "document_chunk") {
    const pageRange =
      source.page_start != null
        ? source.page_end != null && source.page_end !== source.page_start
          ? `p. ${source.page_start}–${source.page_end}`
          : `p. ${source.page_start}`
        : null;
    return (
      <li>
        <strong>{source.title || source.source || "Untitled filing"}</strong>
        {source.company && <> ({source.company})</>}
        {pageRange && <> &middot; {pageRange}</>}
        {source.section && <> &middot; {source.section}</>}
      </li>
    );
  }
  if (source.type === "financial_metrics" || source.type === "financial_facts") {
    return (
      <li>
        {source.field ? metricLabel(source.field) : "Metric"}
        {source.company && <> &middot; {source.company}</>}
        {source.symbols && <> &middot; {source.symbols.join(", ")}</>}
        {source.period && <> &middot; {source.period}</>}
        {source.filing_type && <> ({source.filing_type})</>}
      </li>
    );
  }
  
  return (
    <li>
      {source.type}
      {source.company && <> &middot; {source.company}</>}
      {source.filing_type && <> ({source.filing_type})</>}
    </li>
  );
}

function ClassificationLine({ classification }) {
  const { companies, metrics, filing_type: filingType, confidence } = classification;
  return (
    <p className="muted" style={{ margin: "0.3rem 0 0" }}>
      {companies?.length > 0 && <>companies: {companies.join(", ")} &middot; </>}
      {metrics?.length > 0 && <>metrics: {metrics.map(metricLabel).join(", ")} &middot; </>}
      filing: {filingType} &middot; confidence: {confidence}
    </p>
  );
}

function AnswerCard({ message }) {
  const { response } = message;
  return (
    <div className="card">
      <span className="tag">{INTENT_LABELS[response.intent] || response.intent}</span>
      <p style={{ whiteSpace: "pre-wrap", margin: "0.7rem 0 0" }}>{response.answer}</p>
      <ClassificationLine classification={response.classification} />
      {response.warnings?.length > 0 && (
        <ul style={{ color: "var(--loss)", paddingLeft: "1.1rem", marginTop: "0.7rem" }}>
          {response.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
      {response.caveats?.length > 0 && (
        <ul className="muted" style={{ paddingLeft: "1.1rem", marginTop: "0.7rem" }}>
          {response.caveats.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
      {response.sources?.length > 0 && (
        <>
          <h2 style={{ fontSize: "0.85rem", marginTop: "0.9rem" }}>Sources</h2>
          <ul style={{ paddingLeft: "1.1rem", margin: 0, fontSize: "0.88rem" }}>
            {response.sources.map((s, i) => (
              <SourceItem key={i} source={s} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Message({ message }) {
  return (
    <li style={{ marginBottom: "1.3rem" }}>
      <p className="byline" style={{ margin: "0 0 0.2rem" }}>
        You{message.scopeSymbol ? ` (scoped to ${message.scopeSymbol})` : ""}
      </p>
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>{message.question}</p>
      {message.status === "pending" && <StatusBanner loading loadingText="Thinking..." />}
      {message.status === "error" && <StatusBanner error={message.error} />}
      {message.status === "done" && <AnswerCard message={message} />}
    </li>
  );
}

export default function QaPage() {
  usePageTitle("Financial QA");
  const { data: companies } = useApi(() => api.listCompanies(), []);
  const [scopeSymbol, setScopeSymbol] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState([]);
  const logEndRef = useRef(null);

  const isAsking = messages.some((m) => m.status === "pending");

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "end" });
  }, [messages]);

  function ask(question) {
    const trimmed = question.trim();
    if (!trimmed || isAsking) return;
    const id = `${Date.now()}-${Math.random()}`;
    setMessages((prev) => [...prev, { id, question: trimmed, scopeSymbol, status: "pending" }]);
    setInput("");

    const call = scopeSymbol ? api.askCompanyQuestion(scopeSymbol, trimmed) : api.askQuestion(trimmed);
    call
      .then((response) => {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: "done", response } : m)));
      })
      .catch((error) => {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: "error", error } : m)));
      });
  }

  function handleSubmit(e) {
    e.preventDefault();
    ask(input);
  }

  return (
    <div>
      <div className="page-header">
        <h1>Financial QA</h1>
        <select value={scopeSymbol} onChange={(e) => setScopeSymbol(e.target.value)} aria-label="Scope question to a company">
          <option value="">All companies (general)</option>
          {(companies || []).map((c) => (
            <option key={c.symbol} value={c.symbol}>
              {c.symbol} &mdash; {c.name}
            </option>
          ))}
        </select>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        Answers are grounded in this project's own verified data and filings -- every claim comes with a
        cited source below it, never an unsupported number.
      </p>

      {messages.length === 0 && (
        <div role="group" aria-label="Example questions" style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", marginBottom: "1.1rem" }}>
          {EXAMPLE_QUESTIONS.map((q) => (
            <button key={q} type="button" className="tag example-chip" onClick={() => ask(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      {messages.length > 0 && (
        <>
          <ul role="log" aria-live="polite" aria-relevant="additions" style={{ listStyle: "none", padding: 0, margin: "1.1rem 0" }}>
            {messages.map((m) => (
              <Message key={m.id} message={m} />
            ))}
          </ul>
          <div ref={logEndRef} aria-hidden="true" />
        </>
      )}

      <form onSubmit={handleSubmit} style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", marginTop: "1.1rem" }}>
        <label htmlFor="qa-input" className="visually-hidden">
          Your question
        </label>
        <input
          id="qa-input"
          type="text"
          className="qa-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a financial question, e.g. 'What is TCS's revenue growth?'"
          disabled={isAsking}
        />
        <button type="submit" className="qa-ask-button" disabled={isAsking || !input.trim()}>
          Ask
        </button>
      </form>
    </div>
  );
}