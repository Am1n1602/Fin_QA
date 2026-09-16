"""Baseline B (§40): Question -> Vector Search -> LLM. No Financial Engine, no calculator,
no verification -- pure dense retrieval + synthesis. See docs/file-guide.md."""
from __future__ import annotations

from time import perf_counter

from finqa_v2.evidence.build import evidence_from_retrieved_chunk

SYSTEM = (
    "Answer the financial question using ONLY the passages below, each labelled [n]. "
    "If the passages do not contain the answer, say the evidence is insufficient. Do not "
    "use outside knowledge or invent figures."
)


def answer(question: str, retriever, repos, provider, *, k: int = 5) -> dict:
    t0 = perf_counter()
    hits = retriever.retrieve(question, k=k, candidate_k=30, mode="vector", rerank=False)
    if not hits:
        return {
            "response": {"answer": "No relevant passages were found.", "claims": [],
                         "evidence": [], "calculations": [], "sources": [], "confidence": 0.1},
            "verification": {}, "plan": {"intent": None}, "trace": [],
            "llm_used": False, "latency_ms": (perf_counter() - t0) * 1000,
        }
    evs = [evidence_from_retrieved_chunk(h, repos=repos) for h in hits]
    context = "\n\n".join(f"[{i}] {(e.text or '')[:800]}" for i, e in enumerate(evs))
    text = provider.complete(f"Passages:\n{context}\n\nQuestion: {question}", system=SYSTEM,
                             temperature=0.2, max_tokens=350)
    sources = [e.citation.to_dict() for e in evs if e.citation]
    return {
        "response": {"answer": (text or "").strip(), "claims": [],
                     "evidence": [e.to_dict() for e in evs], "calculations": [],
                     "sources": sources, "confidence": 0.5},
        "verification": {}, "plan": {"intent": None}, "trace": [],
        "llm_used": True, "latency_ms": (perf_counter() - t0) * 1000,
    }
