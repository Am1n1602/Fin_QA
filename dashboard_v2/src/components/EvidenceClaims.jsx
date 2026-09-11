import React from "react";

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
  if (value === null || value === undefined) return "N/A";
  const num = typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value;
  return unit ? `${num} ${unit}` : `${num}`;
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
  return (
    <li className="evidence-row">
      {isDescriptive ? (
        <span className="evidence-head">{ev.text}</span>
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
      <span className="evidence-confidence" title="Retrieval/derivation confidence">
        {Math.round((ev.confidence ?? 0) * 100)}%
      </span>
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
  const { claim, evidence = [], calculations = [], sources = [], confidence_breakdown: cb } = node;
  const numericEvidence = evidence.filter((e) => e.value !== null && e.value !== undefined);
  const docEvidence = evidence.filter((e) => e.value === null || e.value === undefined);

  return (
    <details className="claim-card">
      <summary className="claim-summary">
        <StatusBadge status={claim.status} />
        <span className="claim-text">{claim.text}</span>
        <span className="claim-confidence">{Math.round((claim.confidence ?? 0) * 100)}%</span>
      </summary>

      <div className="claim-body">
        {numericEvidence.length > 0 && (
          <section className="claim-section">
            <h4>Supporting numbers</h4>
            <ul className="evidence-list">
              {numericEvidence.map((e) => (
                <EvidenceRow key={e.evidence_id} ev={e} />
              ))}
            </ul>
          </section>
        )}

        {calculations.length > 0 && (
          <section className="claim-section">
            <h4>Calculations</h4>
            <ul className="calc-list">
              {calculations.map((c) => (
                <CalculationRow key={c.calculation_id} calc={c} />
              ))}
            </ul>
          </section>
        )}

        {docEvidence.length > 0 && (
          <section className="claim-section">
            <h4>Evidence</h4>
            <ul className="evidence-list">
              {docEvidence.map((e) => (
                <EvidenceRow key={e.evidence_id} ev={e} />
              ))}
            </ul>
          </section>
        )}

        {sources.length > 0 && (
          <section className="claim-section">
            <h4>Sources</h4>
            <div className="source-chips">
              {sources.map((s) => (
                <SourceChip key={s.citation_id} source={s} />
              ))}
            </div>
          </section>
        )}

        {cb && (
          <p className="claim-confidence-note">
            confidence = mean support ({cb.mean_support}) &times; status factor ({cb.status_factor}) ={" "}
            {cb.claim_confidence}
          </p>
        )}
      </div>
    </details>
  );
}

export function ClaimList({ claims }) {
  if (!claims || claims.length === 0) return null;
  return (
    <section className="claim-list" aria-label="Claims, with supporting evidence">
      <h3>Key findings</h3>
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

export default function EvidenceAnswer({ result }) {
  const { response, claim_graph: claimGraph } = result;
  return (
    <div className="evidence-answer">
      <p className="answer-text">{response.answer}</p>
      <p className="answer-confidence">
        Overall confidence: <strong>{Math.round((response.confidence ?? 0) * 100)}%</strong>
      </p>
      <VerificationNote verification={result.verification} />
      <LimitationsList items={response.limitations} />
      <ClaimList claims={claimGraph?.claims} />
    </div>
  );
}
