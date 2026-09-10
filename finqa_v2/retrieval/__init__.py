"""Hybrid retrieval: metadata filter + BM25 + vector -> RRF -> rerank (§16-17).
See docs/file-guide.md."""
from __future__ import annotations

from .embed import Embedder, HashEmbedder, SentenceTransformerEmbedder
from .fuse import reciprocal_rank_fusion
from .lexical import BM25Index
from .rerank import CrossEncoderReranker, IdentityReranker, Reranker
from .retriever import HybridRetriever, RetrievedChunk
from .vector import VectorIndex

__all__ = [
    "BM25Index",
    "CrossEncoderReranker",
    "Embedder",
    "HashEmbedder",
    "HybridRetriever",
    "IdentityReranker",
    "Reranker",
    "RetrievedChunk",
    "SentenceTransformerEmbedder",
    "VectorIndex",
    "reciprocal_rank_fusion",
]
