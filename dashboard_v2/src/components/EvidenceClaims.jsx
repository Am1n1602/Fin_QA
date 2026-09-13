import React from "react";
import { formatValue } from "../utils/format.js";
import { renderAnswerHtml, reformatCurrencyNumbers } from "../utils/answerFormat.js";

/* The v2 differentiator (roadmap §24/§32): every claim in an answer traces back to the
   exact evidence, calculation, and filing passage that supports it. `claims` here is
   `claim_graph.claims` -- each entry is already a fully-resolved provenance subtree
   (finqa_v2/claimgraph/view.py's ClaimGraphView.explain()), so no client-side id lookups
   are needed. Rendered as native <details> -- accessible, keyboard-operable, no JS state. */

const STATUS_META = {
  supported: { label: "Supported", className: "status-supported" },
  partially_supported: { label: "Partially supported", className: "status-partial" },
  not_supported: { label: "Not supported", className: "status-not-supported" },
  insufficient_evidence: { label: "Insufficient evidence", className: "status-insufficient" },
};

function StatusBadge({ status }) {
  const meta = STATUS_META[status] || { label: status, className: "status-unknown" };
  return <span className={`status-badge ${meta.className}`}>{meta.label}</span>;
}

function fmtValue(value, unit) {
  return formatValue(value, unit) === "—" ? "N/A" : formatValue(value, unit);
}

function EvidenceRow({ ev }) {
  const isNumeric = ev.value !== null && ev.value !== undefined;
  // Segment and comparison/ranking evidence's own `metric` is a generic literal
  // ("segment_revenue", or the raw ranked metric name) shared by every row of that
  // kind -- `text` is the one place the real distinguishing detail lives (the segment
  // name, or "<ticker> ranked #N on ..."), and is already a full self-contained
  // sentence (see finqa_v2/evidence/build.py), so show it alone rather than a
  // duplicate value badge next to a nameless heading.
  const isDescriptive = ev.type === "segment" || ev.type === "comparison";
  const head = [ev.company, ev.metric, ev.period && `(${ev.period})`].filter(Boolean).join(" ");
  const confidenceTitle = `Retrieval/derivation confidence: ${Math.round((ev.confidence ?? 0) * 100)}%`;
  return (
    <li className="evidence-row" title={confidenceTitle}>
      {isDescriptive ? (
        <span className="evidence-head">{reformatCurrencyNumbers(ev.text)}</span>
      ) : isNumeric ? (
        <>
          <span className="evidence-head">{head || ev.type}</span>
          <span className="evidence-value">{fmtValue(ev.value, ev.unit)}</span>
        </>
      ) : (
        <>
          <span className="evidence-head">{ev.source?.label || head || ev.type}</span>
          {ev.text && <p className="evidence-snippet">&ldquo;{ev.text}&rdquo;</p>}
        </>
      )}
    </li>
  );
}

function CalculationRow({ calc }) {
  return (
    <li className="calc-row">
      <div className="calc-head">
        <strong>{calc.name}</strong> = {fmtValue(calc.result, calc.unit)}
      </div>
      {calc.expression && <code className="calc-expression">{calc.expression}</code>}
      {calc.inputs?.length > 0 && (
        <ul className="calc-inputs">
          {calc.inputs.map((inp, i) => (
            <li key={i}>
              {inp.name} = {fmtValue(inp.value, inp.unit)}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function SourceChip({ source }) {
  return <span className="source-chip">{source.label}</span>;
}

function ClaimCard({ claim: node }) {
  const { claim, evidence = [], calculations = [], sources = [] } = node;
  const numericEvidence = evidence.filter((e) => e.value !== null && e.value !== undefined);
  const docEvidence = evidence.filter((e) => e.value === null || e.value === undefined);

  return (
    <details className="claim-card">
      <summary className="claim-summary" title={`Claim confidence: ${Math.round((claim.confidence ?? 0) * 100)}%`}>
        <StatusBadge status={claim.status} />
        <span className="claim-text">{reformatCurrencyNumbers(claim.text)}</span>
      </summary>

      <div className="claim-body">
        {numericEvidence.length > 0 && (
          <section className="claim-section">
            <h3>Supporting numbers</h3>
            <ul className="evidence-list">
              {numericEvidence.map((e) => (
                <EvidenceRow key={e.evidence_id} ev={e} />
              ))}
            </ul>
          </section>
        )}

        {calculations.length > 0 && (
          <section className="claim-section">
            <h3>Calculations</h3>
            <ul className="calc-list">
              {calculations.map((c) => (
                <CalculationRow key={c.calculation_id} calc={c} />
              ))}
            </ul>
          </section>
        )}

        {docEvidence.length > 0 && (
          <section className="claim-section">
            <h3>Evidence</h3>
            <ul className="evidence-list">
              {docEvidence.map((e) => (
                <EvidenceRow key={e.evidence_id} ev={e} />
              ))}
            </ul>
          </section>
        )}

        {sources.length > 0 && (
          <section className="claim-section">
            <h3>Sources</h3>
            <div className="source-chips">
              {sources.map((s) => (
                <SourceChip key={s.citation_id} source={s} />
              ))}
            </div>
          </section>
        )}
      </div>
    </details>
  );
}

export function ClaimList({ claims, contextLabel }) {
  if (!claims || claims.length === 0) return null;
  // Distinguishes this landmark's accessible name when more than one answer is on screen
  // at once (QaPage keeps a running log of questions) -- axe-core: landmark-unique.
  const label = contextLabel
    ? `Claims, with supporting evidence, for: ${contextLabel}`
    : "Claims, with supporting evidence";
  return (
    <section className="claim-list" aria-label={label}>
      <h2>Key findings</h2>
      {claims.map((node) => (
        <ClaimCard key={node.claim.claim_id} claim={node} />
      ))}
    </section>
  );
}

export function LimitationsList({ items }) {
  if (!items || items.length === 0) return null;
  return (
    <ul className="limitations-list">
      {items.map((l, i) => (
        <li key={i}>{l}</li>
      ))}
    </ul>
  );
}

export function VerificationNote({ verification }) {
  if (!verification) return null;
  const { status, counts } = verification;
  if (status === "passed" && (!counts || Object.keys(counts).length === 0)) return null;
  return (
    <p className={`verification-note verification-${status}`}>
      Verification: <strong>{status.replace(/_/g, " ")}</strong>
      {counts && Object.keys(counts).length > 0 && (
        <span className="verification-counts">
          {" "}
          ({Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(", ")})
        </span>
      )}
    </p>
  );
}

export default function EvidenceAnswer({ result, contextLabel }) {
  const { response, claim_graph: claimGraph } = result;
  return (
    <div className="evidence-answer" title={`Overall confidence: ${Math.round((response.confidence ?? 0) * 100)}%`}>
      <div className="answer-text" dangerouslySetInnerHTML={{ __html: renderAnswerHtml(response.answer) }} />
      <VerificationNote verification={result.verification} />
      <LimitationsList items={response.limitations} />
      <ClaimList claims={claimGraph?.claims} contextLabel={contextLabel} />
    </div>
  );
}
