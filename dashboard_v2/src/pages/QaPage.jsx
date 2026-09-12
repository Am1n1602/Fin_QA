import React, { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";
import { useApi } from "../api/useApi.js";
import { usePageTitle } from "../hooks/usePageTitle.js";
import StatusBanner from "../components/StatusBanner.jsx";
import EvidenceAnswer from "../components/EvidenceClaims.jsx";

const EXAMPLE_QUESTIONS = [
  "What was TCS's revenue in FY2026?",
  "Compare TCS and Infosys on profitability.",
  "Which segment contributed most to Reliance's revenue growth?",
  "Why did HCLTECH's profitability decline?",
  "TCS management said growth was driven by the BFSI segment. Is this supported?",
];

function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function Message({ message }) {
  return (
    <div className="qa-message">
      <p className="byline" style={{ margin: "0 0 0.2rem" }}>
        You
      </p>
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>{message.question}</p>
      {message.status === "pending" && <StatusBanner loading loadingText="Thinking..." />}
      {message.status === "error" && <StatusBanner error={message.error} />}
      {message.status === "done" && (
        <div className="card">
          <EvidenceAnswer result={message.result} contextLabel={message.question} />
        </div>
      )}
    </div>
  );
}

export default function QaPage() {
  usePageTitle("Financial QA");
  useApi(() => api.health(), []); // warms the connection; not displayed here
  const [useLlm, setUseLlm] = useState(true);
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
    setMessages((prev) => [...prev, { id, question: trimmed, status: "pending" }]);
    setInput("");

    api
      .askQuestion(trimmed, { useLlm })
      .then((result) => {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, status: "done", result } : m)));
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
        <label className="checkbox-inline">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
          Use LLM synthesis
        </label>
      </div>
      <p className="byline" style={{ marginTop: 0 }}>
        Answers are grounded in the Financial Engine and this project's own filings. Expand
        any finding below to see the exact evidence, calculation, and source behind it &mdash;
        never an unsupported number.
      </p>

      {messages.length === 0 && (
        <div role="group" aria-label="Example questions" className="example-chips">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button key={q} type="button" className="tag example-chip" onClick={() => ask(q)}>
              {q}
            </button>
          ))}
        </div>
      )}

      {messages.length > 0 && (
        <>
          {/* role="log" is a live-region role, not a list container -- ARIA doesn't allow it
              on <ul> (whose implicit role is "list"), and that mismatch also orphaned the
              <li> children's listitem semantics (axe-core: aria-allowed-role, listitem). A
              plain <div> is the correct host per the ARIA APG log pattern. */}
          <div role="log" aria-live="polite" aria-relevant="additions" className="qa-log">
            {messages.map((m) => (
              <Message key={m.id} message={m} />
            ))}
          </div>
          <div ref={logEndRef} aria-hidden="true" />
        </>
      )}

      <form onSubmit={handleSubmit} className="qa-form">
        <label htmlFor="qa-input" className="visually-hidden">
          Your question
        </label>
        <input
          id="qa-input"
          type="text"
          className="qa-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a financial question, e.g. 'What was TCS's revenue in FY2026?'"
          disabled={isAsking}
        />
        <button type="submit" className="qa-ask-button" disabled={isAsking || !input.trim()}>
          Ask
        </button>
      </form>
    </div>
  );
}
