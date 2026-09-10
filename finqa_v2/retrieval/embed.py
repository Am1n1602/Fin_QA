"""Embedders (§16 semantic path). `Embedder.encode` returns an (n, dim) float32 array
of L2-normalized row vectors so cosine similarity is a dot product.

- HashEmbedder: deterministic hashing-trick embedding, zero heavy deps. Cheap, always
  available; good enough to exercise the vector + hybrid code paths and tests.
- SentenceTransformerEmbedder: the real model (all-mpnet-base-v2); lazy torch import.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence, runtime_checkable

from finqa_v2.retrieval.tokenize import tokenize

_WORD = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def encode(self, texts: Sequence[str]): ...


class HashEmbedder:
    name = "hash"

    def __init__(self, dim: int = 256):
        self.dim = dim

    def encode(self, texts: Sequence[str]):
        import numpy as np

        mat = np.zeros((len(texts), self.dim), dtype="float32")
        for row, text in enumerate(texts):
            for tok in tokenize(text):
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "little")
                idx = h % self.dim
                sign = 1.0 if (h >> 63) & 1 else -1.0
                mat[row, idx] += sign
            norm = math.sqrt(float((mat[row] ** 2).sum()))
            if norm > 0:
                mat[row] /= norm
        return mat


class SentenceTransformerEmbedder:
    name = "all-mpnet-base-v2"

    def __init__(self, model_name: str = "all-mpnet-base-v2", device: str = "cpu"):
        self.model_name = model_name
        self.device = device
        self._model = None

    def _get(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # lazy: pulls torch

            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dim(self) -> int:
        return int(self._get().get_sentence_embedding_dimension())

    def encode(self, texts: Sequence[str]):
        return (
            self._get()
            .encode(list(texts), normalize_embeddings=True, convert_to_numpy=True, batch_size=32)
            .astype("float32")
        )
