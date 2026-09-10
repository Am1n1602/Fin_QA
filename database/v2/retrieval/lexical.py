"""BM25 lexical index over document_chunks (§16). Pure Python (rank-bm25) -- no torch."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

from database.v2.retrieval.filters import compile_filter
from database.v2.retrieval.tokenize import tokenize

_META_KEYS = ("company_id", "financial_year", "document_type", "section", "segment", "topic")


@dataclass(frozen=True, slots=True)
class BM25Hit:
    chunk_id: int
    score: float


class BM25Index:
    def __init__(self, chunk_ids: list[int], corpus_tokens: list[list[str]], meta: list[dict]):
        from rank_bm25 import BM25Okapi

        self.chunk_ids = chunk_ids
        self.meta = meta
        self._bm25 = BM25Okapi(corpus_tokens) if corpus_tokens else None

    # ------------------------------------------------------------------ #
    @classmethod
    def build(cls, repos) -> "BM25Index":
        rows = repos.connection.execute(
            f"SELECT chunk_id, text, {', '.join(_META_KEYS)} FROM document_chunks ORDER BY chunk_id"
        ).fetchall()
        ids = [r["chunk_id"] for r in rows]
        toks = [tokenize(r["text"]) for r in rows]
        meta = [{k: r[k] for k in _META_KEYS} for r in rows]
        return cls(ids, toks, meta)

    def __len__(self) -> int:
        return len(self.chunk_ids)

    def search(self, query: str, k: int = 30, *, filters: dict | None = None) -> list[BM25Hit]:
        if self._bm25 is None or not self.chunk_ids:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        keep = compile_filter(filters)
        order = sorted(range(len(self.chunk_ids)), key=lambda i: scores[i], reverse=True)
        out: list[BM25Hit] = []
        for i in order:
            if scores[i] <= 0:
                break
            if not keep(self.meta[i]):
                continue
            out.append(BM25Hit(self.chunk_ids[i], float(scores[i])))
            if len(out) >= k:
                break
        return out

    # ------------------------------------------------------------------ #
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"chunk_ids": self.chunk_ids, "meta": self.meta, "bm25": self._bm25}, f)

    @classmethod
    def load(cls, path: str | Path) -> "BM25Index":
        with open(path, "rb") as f:
            d = pickle.load(f)
        obj = cls.__new__(cls)
        obj.chunk_ids = d["chunk_ids"]
        obj.meta = d["meta"]
        obj._bm25 = d["bm25"]
        return obj
