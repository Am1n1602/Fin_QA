"""Operational scoring (§39): P50/P95 latency, retrieval latency, LLM tokens + cost/query. See docs/file-guide.md."""
from __future__ import annotations

import statistics
from typing import Any

# $ per 1M tokens (prompt, completion). Groq free tier -> 0. Override via OperationsEvaluator(pricing=).
PRICING: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-120b": (0.0, 0.0),
    "llama-3.3-70b-versatile": (0.0, 0.0),
}

_RETRIEVAL_TOOLS = {"search_documents", "get_document_section"}


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


class OperationsEvaluator:
    """Aggregate-only. `run(rows)` where each row has `latency_ms`, `trace`, `llm` (usage delta)."""

    name = "operations"

    def __init__(self, model: str | None = None, pricing: dict | None = None) -> None:
        self.model = model
        self.pricing = pricing or PRICING

    def _cost(self, prompt_tok: int, completion_tok: int) -> float:
        rate = self.pricing.get(self.model or "", (0.0, 0.0))
        return round(prompt_tok / 1e6 * rate[0] + completion_tok / 1e6 * rate[1], 6)

    def run(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
        retr_lat: list[float] = []
        tool_calls = 0
        for r in rows:
            for c in r.get("trace") or []:
                tool_calls += 1
                if c.get("tool") in _RETRIEVAL_TOOLS:
                    retr_lat.append(c.get("latency_ms", 0.0))
        p_tok = sum((r.get("llm") or {}).get("prompt_tokens", 0) for r in rows)
        c_tok = sum((r.get("llm") or {}).get("completion_tokens", 0) for r in rows)
        n_llm = sum(1 for r in rows if (r.get("llm") or {}).get("total_tokens", 0) > 0)
        n = len(rows) or 1
        return {
            "n_questions": len(rows),
            "latency_ms": {
                "mean": round(statistics.fmean(lat), 2) if lat else None,
                "p50": _pct(lat, 0.50), "p95": _pct(lat, 0.95),
                "max": round(max(lat), 2) if lat else None,
            },
            "retrieval_latency_ms": {
                "mean": round(statistics.fmean(retr_lat), 2) if retr_lat else None,
                "p50": _pct(retr_lat, 0.50), "p95": _pct(retr_lat, 0.95),
                "n_calls": len(retr_lat),
            },
            "tool_calls_total": tool_calls,
            "tool_calls_per_question": round(tool_calls / n, 2),
            "llm": {
                "model": self.model,
                "questions_using_llm": n_llm,
                "prompt_tokens": p_tok,
                "completion_tokens": c_tok,
                "total_tokens": p_tok + c_tok,
                "tokens_per_question": round((p_tok + c_tok) / n, 1),
                "est_cost_usd_total": self._cost(p_tok, c_tok),
                "est_cost_usd_per_question": round(self._cost(p_tok, c_tok) / n, 8),
            },
        }
