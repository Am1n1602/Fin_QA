"""Cross-encoder reranker (§17): score (query, passage) pairs to reorder the top
candidates. Identity reranker keeps input order (used when no model is loaded).
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Higher = more relevant. Same length as `passages`."""


class IdentityReranker:
    name = "identity"
    trivial = True

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        # descending so the caller's stable sort preserves the incoming order
        return [float(-i) for i in range(len(passages))]


class CrossEncoderReranker:
    name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    trivial = False

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    def _get(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder  # lazy: pulls torch

            self._model = CrossEncoder(self.model_name, device=self.device)
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        return [float(x) for x in self._get().predict([(query, p) for p in passages])]
