"""BM25 lexical index over document_chunks (§16). Pure Python (rank-bm25) -- no torch."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

from finqa_v2.retrieval.filters import compile_filter
from finqa_v2.retrieval.tokenize import tokenize

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

    # -- lazily-built inverted index over the cheap metadata keys, so a company /
    #    year / section filter is a set lookup instead of an O(N) scan over `meta`.
    _INDEXED_KEYS = ("company_id", "financial_year", "document_type", "section")

    def _meta_index(self) -> dict:
        idx = getattr(self, "_mi", None)
        if idx is None:
            idx = {kk: {} for kk in self._INDEXED_KEYS}
            for pos, m in enumerate(self.meta):
                for kk in self._INDEXED_KEYS:
                    idx[kk].setdefault(m.get(kk), []).append(pos)
            self._mi = idx
        return idx

    def _kept_positions(self, filters: dict) -> list[int] | None:
        """Positions matching `filters` via the inverted index, or None if any filter
        key/shape isn't index-backed (caller falls back to the linear scan)."""
        mi = self._meta_index()
        sets: list[set[int]] = []
        for key, want in filters.items():
            if key not in mi:
                return None
            vals = want if isinstance(want, (list, tuple, set)) else [want]
            s: set[int] = set()
            for v in vals:
                s.update(mi[key].get(v, ()))
            sets.append(s)
        if not sets:
            return None
        keep = set.intersection(*sets) if len(sets) > 1 else sets[0]
        return sorted(keep)

    def search(self, query: str, k: int = 30, *, filters: dict | None = None) -> list[BM25Hit]:
        if self._bm25 is None or not self.chunk_ids:
            return []
        qtoks = tokenize(query)
        n = len(self.chunk_ids)

        # §16 step 1: apply the metadata filter BEFORE scoring. When it restricts the
        # corpus to a meaningful subset (e.g. one company's ~1/N of the chunks), score
        # only those docs -- turns O(all chunks) into O(kept), which is what keeps
        # per-query latency ~flat as the universe grows.
        if filters:
            kept = self._kept_positions(filters)
            if kept is None:                          # filter not fully index-backed
                keep = compile_filter(filters)
                kept = [i for i in range(n) if keep(self.meta[i])]
            if not kept:
                return []
            if len(kept) <= 0.6 * n:
                sub = self._bm25.get_batch_scores(qtoks, kept)
                pairs = sorted(zip(kept, sub), key=lambda x: x[1], reverse=True)
                return [BM25Hit(self.chunk_ids[i], float(s)) for i, s in pairs[:k] if s > 0]

        scores = self._bm25.get_scores(qtoks)
        keep = compile_filter(filters)
        order = sorted(range(n), key=lambda i: scores[i], reverse=True)
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
