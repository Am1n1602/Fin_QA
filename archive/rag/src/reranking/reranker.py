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