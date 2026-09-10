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
             EvidenceType.SEGMENT, EvidenceType.CALCULATION)


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


def build_prompt(question: str, plan, workspace) -> str:
    return f"""Question: {question}
Planned intent: {plan.intent.value}

Evidence Workspace
------------------
{render_workspace(workspace)}

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


def deterministic_answer(question: str, plan, workspace) -> dict:
    """No-LLM fallback: state the facts, one claim each, flag the gap for 'why' questions."""
    facts = [e for e in workspace if e.type in _FACTLIKE and e.value is not None]
    docs = workspace.documents()
    sentences = []
    claims = []
    for e in facts[:6]:
        head = " ".join(x for x in (e.company, (e.metric or e.type.value).replace("_", " "),
                                    f"in {e.period}" if e.period else "") if x)
        sentences.append(f"{head} was {_fmt_value(e.value, e.unit)}.")
        claims.append({"text": sentences[-1], "kind": "numeric", "evidence_ids": [e.evidence_id]})
    limitations = ["Answer assembled directly from retrieved evidence; no LLM synthesis was run."]
    if plan.intent.value in ("causal", "cross_validation") and not docs:
        limitations.append("No supporting document passages were retrieved, so the cause is not established.")
    if not sentences:
        sentences.append("The available evidence was not sufficient to answer this question.")
    return {"answer": " ".join(sentences), "key_findings": sentences[:],
            "claims": claims, "limitations": limitations}
