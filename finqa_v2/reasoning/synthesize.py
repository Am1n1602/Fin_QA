"""Reasoning-LLM prompt, response parsing, and the deterministic fallback answer.

The LLM only ever synthesizes from the Evidence Workspace it is given (§21). The
fallback stitches the evidence into a plain answer -- it invents nothing.
"""
from __future__ import annotations

import json
import re

from finqa_v2.evidence.models import EvidenceType

SYSTEM = (
    "You are the reasoning layer of a deterministic financial-analysis engine for Indian "
    "listed companies. You are given a question and an Evidence Workspace (facts, "
    "calculations, and document passages, each with an evidence_id). Write the answer "
    "USING ONLY that evidence. Do NOT invent numbers, do NOT compute new figures, do NOT "
    "invent citations or management statements, do NOT fill missing data. Every numeric or "
    "causal claim must reference the evidence_id(s) it rests on. If the evidence is "
    "insufficient to answer, say so plainly and list what is missing."
)

_FACTLIKE = (EvidenceType.FINANCIAL_FACT, EvidenceType.RATIO, EvidenceType.GROWTH,
             EvidenceType.SEGMENT, EvidenceType.CALCULATION, EvidenceType.COMPARISON)
# Evidence whose own `text` is already a full, self-contained descriptive sentence
# (segment name, or "<ticker> ranked #N on <metric>") -- genericizing it to
# "{company} {metric} = {value}" would show identical, nameless rows for every segment
# or every ranked company (see evidence/build.py).
_DESCRIPTIVE = (EvidenceType.SEGMENT, EvidenceType.COMPARISON)


def _fmt_value(v, unit) -> str:
    if v is None:
        return "N/A"
    s = f"{v:,.2f}" if isinstance(v, float) else str(v)
    return f"{s} {unit}".strip() if unit else s


def render_workspace(workspace) -> str:
    facts = [e for e in workspace if e.type in _FACTLIKE]
    docs = workspace.documents()
    lines: list[str] = []
    if facts:
        lines.append("FACTS & CALCULATIONS:")
        for e in facts:
            if e.type in _DESCRIPTIVE:
                period = f" ({e.period})" if e.period else ""
                lines.append(f"  ({e.evidence_id}) {e.text}{period}".strip())
            else:
                head = " ".join(x for x in (e.company, e.metric or e.type.value,
                                            f"({e.period})" if e.period else "") if x)
                tail = f"  [{e.formula}]" if e.formula else ""
                lines.append(f"  ({e.evidence_id}) {head} = {_fmt_value(e.value, e.unit)}{tail}")
            for lim in e.limitations:
                lines.append(f"      note: {lim}")
    if docs:
        lines.append("")
        lines.append("DOCUMENT PASSAGES:")
        for e in docs:
            cite = e.citation.label() if e.citation else f"doc#{e.document_id} p{e.page}"
            snippet = re.sub(r"\s+", " ", (e.text or "")).strip()[:500]
            lines.append(f"  ({e.evidence_id}) [{cite}] {snippet}")
    return "\n".join(lines) or "(no evidence was gathered)"


def build_prompt(question: str, plan, workspace, *, analysis: str | None = None) -> str:
    analysis_block = (f"\n\nDeeper analysis (already classified against the numbers)\n"
                      f"------------------------------------------------------\n{analysis}\n\n"
                      "Explain the SUPPORTED / PARTIALLY_SUPPORTED findings, do not re-open a "
                      "NOT_SUPPORTED one, and say plainly what stays uncertain."
                      ) if analysis else ""
    return f"""Question: {question}
Planned intent: {plan.intent.value}

Evidence Workspace
------------------
{render_workspace(workspace)}{analysis_block}

Return a JSON object exactly like:
{{
  "answer": "2-5 sentences answering the question, grounded entirely in the evidence above",
  "key_findings": ["short factual bullet", "..."],
  "claims": [
    {{"text": "one assertion the answer makes",
      "kind": "numeric|causal|comparative|trend|qualitative",
      "evidence_ids": ["ev-...", "..."]}}
  ],
  "limitations": ["what the evidence does NOT establish", "..."]
}}

Only use evidence_ids that appear above. For a "why"/"how" question with no supporting
document passages, keep the answer to what the numbers show and put the missing causal
evidence in "limitations". Output JSON only."""


_JSON = re.compile(r"\{.*\}", re.S)
_KINDS = {"numeric", "causal", "comparative", "trend", "qualitative"}


def parse_synthesis(raw: str, valid_ids: set[str]) -> dict | None:
    m = _JSON.search(raw or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("answer"), str) or not d["answer"].strip():
        return None
    claims = []
    for c in d.get("claims") or []:
        if not isinstance(c, dict) or not isinstance(c.get("text"), str):
            continue
        ids = [i for i in (c.get("evidence_ids") or []) if i in valid_ids]
        kind = c.get("kind") if c.get("kind") in _KINDS else "qualitative"
        claims.append({"text": c["text"].strip(), "kind": kind, "evidence_ids": ids})
    return {
        "answer": d["answer"].strip(),
        "key_findings": [str(x) for x in (d.get("key_findings") or []) if str(x).strip()],
        "claims": claims,
        "limitations": [str(x) for x in (d.get("limitations") or []) if str(x).strip()],
    }


def deterministic_answer(question: str, plan, workspace, *, analysis=None) -> dict:
    """No-LLM fallback: state the facts, one claim each, flag the gap for 'why' questions.

    `analysis` is a HypothesisReport / CrossValidationReport (§22 / §23); when present its
    own verdict lines are the answer.
    """
    if analysis is not None:
        return _deterministic_analysis_answer(analysis)
    all_factlike = [e for e in workspace if e.type in _FACTLIKE]
    facts = [e for e in all_factlike if e.value is not None]
    # A requested metric/period the engine couldn't resolve (e.g. a period outside the
    # data's coverage) still carries a specific, honest reason on the evidence itself
    # (e.g. "dividend_yield: ... not all available for TCS at period=FY2021") -- surface
    # that instead of only a generic "insufficient evidence" with no explanation.
    missing = [e for e in all_factlike if e.value is None]
    # Descriptive evidence (segments, comparison/ranking rows) is rendered separately
    # from the other facts, and in full: each row is its own named entity (see
    # evidence/build.py's e.text), not a value competing with unrelated metrics for a
    # spot in the top-6 -- a company brief should list every segment, and a comparison
    # every ranked company, not silently drop some because other facts were fetched first.
    descriptive_facts = [e for e in facts if e.type in _DESCRIPTIVE]
    other_facts = [e for e in facts if e.type not in _DESCRIPTIVE]
    docs = workspace.documents()
    sentences = []
    claims = []
    for e in other_facts[:6]:
        head = " ".join(x for x in (e.company, (e.metric or e.type.value).replace("_", " "),
                                    f"in {e.period}" if e.period else "") if x)
        sentences.append(f"{head} was {_fmt_value(e.value, e.unit)}.")
        claims.append({"text": sentences[-1], "kind": "numeric", "evidence_ids": [e.evidence_id]})
    for e in descriptive_facts:
        period = f" in {e.period}" if e.period else ""
        sentence = f"{e.text}{period}.".strip()
        sentences.append(sentence)
        claims.append({"text": sentence, "kind": "numeric", "evidence_ids": [e.evidence_id]})
    limitations = ["Answer assembled directly from retrieved evidence; no LLM synthesis was run."]
    for e in missing:
        for lim in e.limitations:
            if lim not in limitations:
                limitations.append(lim)
    if plan.intent.value in ("causal", "cross_validation") and not docs:
        limitations.append("No supporting document passages were retrieved, so the cause is not established.")
    if not sentences:
        sentences.append("The available evidence was not sufficient to answer this question.")
    return {"answer": " ".join(sentences), "key_findings": sentences[:],
            "claims": claims, "limitations": limitations}


def _deterministic_analysis_answer(report) -> dict:
    """No-LLM fallback for §22/§23: the report's own verdict lines are the answer.

    Claims are added to the graph by the orchestrator (with their classified status), so
    this returns none.
    """
    sentences = report.answer_sentences()
    return {"answer": " ".join(sentences),
            "key_findings": sentences[1:] or sentences,
            "claims": [], "limitations": report.answer_limitations()}
