"""Retrieval evaluation (§16 baseline comparison, §39 metrics).

A case gives a query + a loose relevance spec (company / acceptable sections / keywords).
A retrieved chunk counts as relevant when: company matches (if given) AND section is in
`sections` (if given) AND at least one `must_contain` keyword appears in its text.

Reports Recall@{1,3,5,10}, MRR and P50 latency per retrieval mode -- so 'hybrid' can be
measured against 'lexical' / 'vector' rather than assumed better.

    python -m database.v2.retrieval.evaluate [--modes lexical,hybrid] [--filter-company]
        [--cases PATH] [--v2-db PATH] [--bm25 PATH] [--vector-dir PATH]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from database.v2.retrieval.lexical import BM25Index
from database.v2.retrieval.retriever import HybridRetriever
from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[3]
_CASES = Path(__file__).with_name("eval_cases.jsonl")
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC = _ROOT / "database" / "data" / "finqa_v2_vec"

_KS = (1, 3, 5, 10)


def load_cases(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _relevant(chunk, case, company_id: int | None) -> bool:
    if company_id is not None and chunk.company_id != company_id:
        return False
    secs = case.get("sections")
    if secs and chunk.section not in secs:
        return False
    kws = [w.lower() for w in case.get("must_contain", [])]
    if kws:
        low = (chunk.text or "").lower()
        return any(w in low for w in kws)
    return True


def evaluate(retriever: HybridRetriever, repos, cases: list[dict], *,
             modes=("lexical",), filter_company: bool = False) -> dict:
    report: dict = {}
    for mode in modes:
        if mode not in retriever.modes:
            report[mode] = {"skipped": f"mode unavailable (modes={retriever.modes})"}
            continue
        hit_at = {k: 0 for k in _KS}
        rr_sum = 0.0
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
            first = next((h.rank for h in hits if _relevant(h.chunk, case, cid)), None)
            for k in _KS:
                if first is not None and first <= k:
                    hit_at[k] += 1
            rr_sum += (1.0 / first) if first else 0.0
            per_case.append({"id": case["id"], "first_relevant_rank": first})
        n = len(cases)
        report[mode] = {
            "n": n,
            **{f"recall@{k}": round(hit_at[k] / n, 3) for k in _KS},
            "mrr": round(rr_sum / n, 3),
            "p50_ms": round(statistics.median(lat), 1) if lat else None,
            "per_case": per_case,
        }
    return report


def build_retriever(repos, *, bm25_path: Path, vector_dir: Path) -> HybridRetriever:
    bm25 = BM25Index.load(bm25_path) if bm25_path.exists() else BM25Index.build(repos)
    vector = embedder = None
    if vector_dir.exists():
        try:
            from database.v2.retrieval.embed import SentenceTransformerEmbedder
            from database.v2.retrieval.vector import VectorIndex

            vector = VectorIndex.load(vector_dir)
            embedder = SentenceTransformerEmbedder()
        except Exception:
            vector = embedder = None
    return HybridRetriever(repos, bm25=bm25, vector=vector, embedder=embedder)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=Path, default=_CASES)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--bm25", type=Path, default=_BM25)
    ap.add_argument("--vector-dir", type=Path, default=_VEC)
    ap.add_argument("--modes", default="lexical")
    ap.add_argument("--filter-company", action="store_true")
    args = ap.parse_args()

    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")
    cases = load_cases(args.cases)
    repos = SqliteRepositories(args.v2_db)
    try:
        retr = build_retriever(repos, bm25_path=args.bm25, vector_dir=args.vector_dir)
        rep = evaluate(retr, repos, cases,
                       modes=tuple(m.strip() for m in args.modes.split(",")),
                       filter_company=args.filter_company)
    finally:
        repos.close()

    print(f"cases={len(cases)}  retriever.modes={retr.modes}  company_filter={args.filter_company}")
    for mode, m in rep.items():
        if "skipped" in m:
            print(f"  {mode:8s} -- {m['skipped']}")
            continue
        print(f"  {mode:8s} R@1={m['recall@1']} R@3={m['recall@3']} R@5={m['recall@5']} "
              f"R@10={m['recall@10']} MRR={m['mrr']} p50={m['p50_ms']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
