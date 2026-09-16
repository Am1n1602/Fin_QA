"""Layered Text-Correctness Evaluation (§23): keyword coverage alone is insufficient as
the only text-quality signal. Three layers, each a stronger (and more expensive) check
than the last:

Layer 1 -- rule-based: numeric tolerance / keyword coverage. Reuses
`evaluation.evaluators.answer.CorrectnessEvaluator` exactly, unchanged -- this project's
own "no untracked optimization" rule means Layer 1 isn't reinvented, just wrapped as the
base of something bigger.

Layer 2 -- evidence/claim matching: does the answer's own claims trace to evidence that
actually supports them (`evaluators.answer.GroundednessEvaluator`), and, when a record
carries real gold citations, does that evidence match the real gold documents
(`evaluation.citation.evaluator`, §22). Neither check is reinvented here.

Layer 3 -- LLM judge: given (question, gold evidence, generated answer, claims) -- NEVER
the raw answer text alone, per §23's own requirement -- ask an LLM for a correctness
verdict. Optional and off by default (spends real tokens; Layers 1-2 already produce a
complete, well-defined result without it), and it can only ever ADD a "warn" on
disagreement -- it never overrides Layers 1-2's verdict, matching this project's core
rule that numeric/factual truth never comes from the LLM.
"""
from __future__ import annotations

import json
import re
from typing import Any

from evaluation.citation.evaluator import GoldCitation
from evaluation.citation.evaluator import evaluate as evaluate_citations
from evaluation.evaluators.answer import CorrectnessEvaluator, GroundednessEvaluator, _response

_JUDGE_SYSTEM = (
    "You are a strict correctness judge for a financial-analysis assistant. You will be "
    "given a question, the GOLD EVIDENCE that establishes what a correct answer must be "
    "consistent with, a GENERATED ANSWER, and the CLAIMS it makes. Judge correctness ONLY "
    "against the gold evidence provided -- never against your own general knowledge, and "
    "never judge unsupported prose in isolation without checking it against the evidence. "
    "If the gold evidence doesn't cover something the answer asserts, say so instead of "
    "guessing whether it's true."
)

_JSON = re.compile(r"\{.*\}", re.S)


def _fmt_claims(claims: list[dict]) -> str:
    if not claims:
        return "(no claims)"
    return "\n".join(f"- {c.get('text', '')}" for c in claims)


def gold_evidence_text(record: dict[str, Any]) -> str:
    """Whatever verifiable gold this record actually carries -- never invented. Returns a
    plain marker when a record has none, so the LLM judge is told explicitly rather than
    silently reasoning from an empty section."""
    parts = []
    if record.get("reference_value") is not None:
        unit = record.get("reference_unit") or ""
        parts.append(f"Reference value: {record['reference_value']} {unit}".strip())
    if record.get("must_contain"):
        parts.append("Required concepts: " + ", ".join(record["must_contain"]))
    for r in record.get("reference_sources") or []:
        bits = [f"{k}={v}" for k, v in r.items() if v]
        if bits:
            parts.append("Reference source: " + ", ".join(bits))
    return "\n".join(parts) if parts else "(no gold evidence available for this record)"


def build_judge_prompt(question: str, gold_evidence: str, answer: str, claims: list[dict]) -> str:
    return f"""Question: {question}

GOLD EVIDENCE
-------------
{gold_evidence}

GENERATED ANSWER
-----------------
{answer}

CLAIMS THE ANSWER MAKES
------------------------
{_fmt_claims(claims)}

Return a JSON object exactly like:
{{"correct": true|false, "confidence": 0.0-1.0, "reasoning": "one or two sentences, citing the gold evidence"}}
Output JSON only."""


def parse_judge_response(raw: str) -> dict | None:
    m = _JSON.search(raw or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or "correct" not in d:
        return None
    conf = d.get("confidence")
    return {
        "correct": bool(d["correct"]),
        "confidence": float(conf) if isinstance(conf, (int, float)) else None,
        "reasoning": str(d.get("reasoning") or "").strip(),
    }


def run_llm_judge(question: str, record: dict[str, Any], result: dict[str, Any], provider) -> dict | None:
    """`None` means "no verdict" (provider unavailable/failed/malformed reply) -- Layer 3
    is additive and must never block Layers 1-2 from producing a result."""
    resp = _response(result)
    prompt = build_judge_prompt(question, gold_evidence_text(record), resp.get("answer") or "",
                                resp.get("claims") or [])
    try:
        raw = provider.complete(prompt, system=_JUDGE_SYSTEM, json_object=True,
                                temperature=0.0, max_tokens=300)
    except Exception:
        return None
    return parse_judge_response(raw)


class LayeredCorrectnessEvaluator:
    """§23's three layers, combined. `use_llm_judge=True` (default False) additionally
    runs Layer 3 -- spends real tokens via `provider`, so it stays opt-in."""

    name = "layered_correctness"

    def __init__(self, *, use_llm_judge: bool = False, provider=None):
        self._layer1 = CorrectnessEvaluator()
        self._layer2_groundedness = GroundednessEvaluator()
        self._use_llm_judge = use_llm_judge
        self._provider = provider

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        layer1 = self._layer1.score(record, result)
        layer2_ground = self._layer2_groundedness.score(record, result)

        # Most current datasets don't carry per-record gold document ids yet (Phase 16's
        # own finding) -- `reference_document_ids` is an opt-in extension point for a
        # future dataset revision; its absence degrades gracefully to `gold=[]`, which
        # `evaluate_citations` already reports as None-valued metrics, not a false 0.0.
        gold = [GoldCitation(document_id=d) for d in (record.get("reference_document_ids") or [])]
        resp = _response(result)
        evidence_by_id = {e.get("evidence_id"): e for e in (resp.get("evidence") or [])}
        layer2_citation = evaluate_citations(resp.get("claims") or [], evidence_by_id, gold)

        layer3 = None
        if self._use_llm_judge and self._provider is not None:
            layer3 = run_llm_judge(record.get("question", ""), record, result, self._provider)

        l1_ok = layer1["verdict"] in ("pass", "na")
        l2_ok = layer2_ground["verdict"] in ("pass", "na", "warn")
        verdict = "pass" if (l1_ok and l2_ok) else "fail"
        if verdict == "pass" and layer3 is not None and layer3.get("correct") is False:
            verdict = "warn"

        l3_detail = " L3=skipped"
        if layer3 is not None:
            l3_detail = f" L3={'agree' if layer3.get('correct') else 'disagree'}"

        return {
            "metrics": {
                "layer1_rule_based": layer1["metrics"],
                "layer2_groundedness": layer2_ground["metrics"],
                "layer2_citation": layer2_citation,
                "layer3_llm_judge": layer3,
            },
            "verdict": verdict,
            "detail": f"L1={layer1['verdict']} L2={layer2_ground['verdict']}{l3_detail}",
        }
