"""Baseline C (§40): Question -> Financial Engine -> LLM. No documents, no calculator tool,
no verification, no citations -- the right number(s), handed to a prompting LLM with no
other scaffolding. See docs/file-guide.md."""
from __future__ import annotations

from time import perf_counter

from finqa_v2.engine.ratios import SPECS as _RATIO_SPECS
from finqa_v2.engine.ratios import resolve as _resolve_ratio
from finqa_v2.engine.valuation import resolve as _resolve_valuation
from finqa_v2.planner.rules import plan_with_rules

SYSTEM = (
    "You are a financial analyst. You are given one or more figures computed by a "
    "deterministic financial engine, each with its unit and period. Answer the question "
    "using ONLY those figures -- never invent, adjust or recompute a number. If the "
    "figures are insufficient, say so plainly."
)
_RATIO_NAMES = set(_RATIO_SPECS)


def _fetch(engine, ticker: str, metric: str, period: str):
    if _resolve_ratio(metric) in _RATIO_NAMES:
        return engine.get_ratio(ticker, metric, period=period)
    if _resolve_valuation(metric):
        return engine.get_valuation(ticker, metric, period=period)
    return engine.get_metric(ticker, metric, period=period)


def answer(question: str, repos, engine, provider) -> dict:
    t0 = perf_counter()
    plan = plan_with_rules(question, repos=repos)
    period = plan.periods[0] if plan.periods else "latest"
    metrics = plan.metrics or ["revenue"]
    facts: list[str] = []
    for co in plan.companies:
        for m in metrics:
            try:
                res = _fetch(engine, co, m, period)
            except Exception:
                continue
            if res.ok and res.value is not None:
                facts.append(f"{co} {m} in {res.period}: {res.value} {res.unit or ''}".strip())
    if not facts:
        return {
            "response": {"answer": "The financial engine could not resolve a figure for this question.",
                        "claims": [], "evidence": [], "calculations": [], "sources": [], "confidence": 0.1},
            "verification": {}, "plan": {"intent": plan.intent.value}, "trace": [],
            "llm_used": False, "latency_ms": (perf_counter() - t0) * 1000,
        }
    prompt = "Figures:\n" + "\n".join(facts) + f"\n\nQuestion: {question}"
    text = provider.complete(prompt, system=SYSTEM, temperature=0.2, max_tokens=300)
    return {
        "response": {"answer": (text or "").strip(), "claims": [], "evidence": [],
                     "calculations": [], "sources": [], "confidence": 0.6},
        "verification": {}, "plan": {"intent": plan.intent.value}, "trace": [],
        "llm_used": True, "latency_ms": (perf_counter() - t0) * 1000,
    }
