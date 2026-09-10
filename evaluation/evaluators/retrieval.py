"""Retrieval scoring (§39): Recall@k, MRR, nDCG@k over relevance-spec cases. See docs/file-guide.md."""
from __future__ import annotations

import math
import statistics
import time
from pathlib import Path
from typing import Any

from finqa_v2.retrieval.evaluate import _relevant, build_retriever, load_cases

_KS = (1, 3, 5, 10)


def _ndcg(rels: list[int], k: int) -> float:
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))
    ideal = sorted(rels, reverse=True)
    idcg = sum(r / math.log2(i + 2) for i, r in enumerate(ideal[:k]))
    return dcg / idcg if idcg else 0.0


def score_retrieval(retriever, repos, cases: list[dict], *, mode: str = "lexical",
                    filter_company: bool = True) -> dict[str, Any]:
    if mode not in retriever.modes:
        return {"skipped": f"mode '{mode}' unavailable (modes={retriever.modes})"}
    hit_at = {k: 0 for k in _KS}
    rr_sum = 0.0
    ndcg_at = {k: [] for k in _KS}
    lat: list[float] = []
    per_case = []
    for case in cases:
        co = repos.companies.resolve(case["company"]) if case.get("company") else None
        cid = co.company_id if co else None
        filters = {"company_id": cid} if (filter_company and cid) else None
        t0 = time.perf_counter()
        hits = retriever.retrieve(case["query"], k=max(_KS), candidate_k=40,
                                  mode=mode, filters=filters, rerank=True)
        lat.append((time.perf_counter() - t0) * 1000)
        rels = [1 if _relevant(h.chunk, case, cid) else 0 for h in hits]
        first = next((i + 1 for i, r in enumerate(rels) if r), None)
        for k in _KS:
            if first is not None and first <= k:
                hit_at[k] += 1
            ndcg_at[k].append(_ndcg(rels, k))
        rr_sum += (1.0 / first) if first else 0.0
        per_case.append({"id": case["id"], "first_relevant_rank": first,
                         "ndcg@10": round(_ndcg(rels, 10), 4)})
    n = len(cases)
    return {
        "mode": mode, "n": n, "company_filter": filter_company,
        **{f"recall@{k}": round(hit_at[k] / n, 4) for k in _KS},
        "mrr": round(rr_sum / n, 4),
        **{f"ndcg@{k}": round(statistics.fmean(ndcg_at[k]), 4) for k in _KS},
        "p50_ms": round(statistics.median(lat), 2) if lat else None,
        "per_case": per_case,
    }


class RetrievalEvaluator:
    """Aggregate-only evaluator: builds a retriever and scores a relevance-spec case file.
    Not a per-record `Evaluator` — the runner calls `run()` once per report."""

    name = "retrieval"

    def __init__(self, *, v2_db: Path, bm25: Path, vector_dir: Path,
                 cases_path: Path, modes=("lexical",), filter_company: bool = True) -> None:
        self.v2_db, self.bm25, self.vector_dir = v2_db, bm25, vector_dir
        self.cases_path, self.modes, self.filter_company = cases_path, tuple(modes), filter_company

    def run(self, repos) -> dict[str, Any]:
        if not self.cases_path.exists():
            return {"skipped": f"cases file not found: {self.cases_path}"}
        cases = load_cases(self.cases_path)
        retriever = build_retriever(repos, bm25_path=self.bm25, vector_dir=self.vector_dir)
        out: dict[str, Any] = {"cases": len(cases), "modes_available": list(retriever.modes)}
        for mode in self.modes:
            out[mode] = score_retrieval(retriever, repos, cases, mode=mode,
                                        filter_company=self.filter_company)
        return out
