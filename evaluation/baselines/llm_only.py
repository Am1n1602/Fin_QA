"""Baseline A (§40): Question -> LLM -> Answer. No tools, no retrieval, no engine, no
verification -- whatever the model already knows. See docs/file-guide.md."""
from __future__ import annotations

from time import perf_counter

SYSTEM = (
    "You are a financial analyst answering questions about Indian listed companies. "
    "Answer from your own knowledge as best you can in 2-4 sentences. If you are not "
    "confident of a specific figure, say so plainly rather than guessing."
)


def answer(question: str, provider) -> dict:
    t0 = perf_counter()
    text = provider.complete(question, system=SYSTEM, temperature=0.2, max_tokens=350)
    return {
        "response": {"answer": (text or "").strip(), "claims": [], "evidence": [],
                     "calculations": [], "sources": [], "confidence": 0.5},
        "verification": {}, "plan": {"intent": None}, "trace": [],
        "llm_used": True, "latency_ms": (perf_counter() - t0) * 1000,
    }
