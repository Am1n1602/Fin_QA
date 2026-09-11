"""
reranker.py — Stage 9 (RAG): cross-encoder reranking pass.

WHY THIS EXISTS: real testing on HCLTECH's corpus proved semantic search
(even with a larger 768-dim model), plain BM25, and phrase/bigram overlap
ALL fail to reliably surface the actual dividend-declaration sentence above
repeated regulatory boilerplate and numeric-table noise. Each of those
signals scores query and chunk INDEPENDENTLY (a bi-encoder architecture --
embed each side separately, compare vectors/token-sets afterward), which
caps how finely they can discriminate near-duplicate phrasing. A
cross-encoder instead feeds the query and a candidate chunk into the model
TOGETHER, letting it directly attend across both texts -- a fundamentally
stronger signal for exactly this kind of fine discrimination, at the cost
of needing one model inference PER CANDIDATE rather than one embedding per
document (which is why this is a reranking PASS over a small candidate
pool from hybrid_retrieve(), not a replacement for it -- running a
cross-encoder over the whole corpus per query would be far too slow).

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 -- small (~80MB), fast, trained
specifically for query-passage relevance ranking. Deliberately NOT the same
weight class as the embedding model (mpnet-base-v2, ~420MB) -- reranking
only needs to score ~20-50 candidates per query, not embed an entire
corpus, so a much lighter model is the right tradeoff here, and keeps
combined VRAM usage reasonable on a 4GB card.
"""

from __future__ import annotations

DEFAULT_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _resolve_device(device: str) -> str:
    """Same auto-detect logic as embedding/embedder.py's Embedder --
    duplicated rather than imported to keep this module standalone/testable
    without pulling in the embedding module's dependencies."""
    if device != "auto":
        return device
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


class CrossEncoderReranker:
    """Real reranker. Requires network access to download the model on
    first use (cached locally by sentence-transformers after that)."""

    def __init__(self, model_name: str = DEFAULT_CROSS_ENCODER_MODEL, device: str = "auto"):
        from sentence_transformers import CrossEncoder  # deferred import
        self.model_name = model_name
        self.device = _resolve_device(device)
        print(f"Loading cross-encoder '{model_name}' on device='{self.device}'...")
        self.model = CrossEncoder(model_name, device=self.device)

    def rerank(self, query: str, candidates: list[dict], text_key: str = "text") -> list[dict]:
        """
        candidates: list of dicts, each containing at least `text_key`
        (matches the dict shape returned by retrieve.py's retrieval
        functions -- pass their output straight in).

        Returns the SAME dicts in a NEW order (descending cross-encoder
        relevance), with a "rerank_score" key added to each. Does not
        mutate the input list's order, only the dicts' contents.
        """
        if not candidates:
            return []
        pairs = [(query, c[text_key]) for c in candidates]
        scores = self.model.predict(pairs)
        for c, s in zip(candidates, scores):
            c["rerank_score"] = float(s)
        return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)


class MockCrossEncoderReranker:
    """
    TEST-ONLY. Scores each candidate by plain word-overlap count with the
    query -- correct shape and interface for exercising the reranking
    pipeline, but NOT a real cross-encoder signal (no cross-attention, no
    trained relevance model). Exists purely so the plumbing could be
    validated without network access to huggingface.co in this environment.
    NEVER use this for real retrieval quality decisions.
    """

    def rerank(self, query: str, candidates: list[dict], text_key: str = "text") -> list[dict]:
        if not candidates:
            return []
        q_tokens = set(query.lower().split())
        for c in candidates:
            c_tokens = set(c[text_key].lower().split())
            c["rerank_score"] = float(len(q_tokens & c_tokens))
        return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)