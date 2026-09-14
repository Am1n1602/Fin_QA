"""Deterministic retrieval benchmark: Dense vs BM25 vs Hybrid against literal `gold_chunks`
(v2.1 roadmap §5.3/§5.4). This is the "reproducible benchmark command" the Phase 1
acceptance criteria asks for -- every future v2.1 retrieval experiment (embeddings,
chunking, fusion, MMR, ...) is compared against a run of this same command.

    python -m evaluation.run_retrieval_benchmark \\
        --dataset evaluation/datasets/retrieval_v21.json

Relevance is literal: a retrieved chunk counts as relevant iff its chunk_id is in the
case's `gold_chunks`. Cases with empty gold (`adversarial` / `no_evidence`) are excluded
from Recall/MRR/nDCG (there is nothing to recall) but still counted for latency and for a
separate "spurious hit rate" -- how often the retriever returns *something* anyway on a
question that should have no evidence at all, a preview of the Evidence Quality Gate this
benchmark deliberately does not implement (that is Phase P1's job, §21).
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from evaluation.metrics.mrr import mean_reciprocal_rank
from evaluation.metrics.ndcg import mean_ndcg_at_k
from evaluation.metrics.recall import mean_recall_at_k
from finqa_v2.planner.terminology import expand_lexical_query
from finqa_v2.retrieval.evaluate import build_retriever
from finqa_v2.retrieval.section_weights import list_weighted_sections
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATASET = _ROOT / "evaluation" / "datasets" / "retrieval_v21.json"
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC = _ROOT / "database" / "data" / "finqa_v2_vec"
_RESULTS_DIR = _ROOT / "evaluation" / "results"

_KS = (1, 3, 5, 10)
_MODE_LABEL = {"vector": "Dense", "lexical": "BM25", "hybrid": "Hybrid"}


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(_ROOT), text=True).strip()
    except Exception:
        return "unknown"


def load_dataset(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _company_id(repos, tickers: list[str] | None) -> int | None:
    """Only single-company records get a company filter -- a `comparison` record names
    two tickers and must search across both, not be narrowed to whichever is first."""
    if not tickers or len(tickers) != 1:
        return None
    co = repos.companies.resolve(tickers[0])
    return co.company_id if co else None


def _multi_query_hits(retriever, repos, rec: dict, *, mode: str, rerank: bool,
                      intent: str | None, query_expansion: bool):
    """§8/§9: for a multi-company record, retrieve once PER company (mirroring
    `finqa_v2.planner.decompose.decompose()`'s comparison branch) and merge by
    chunk_id, keeping each chunk's best (lowest) rank across the sub-queries -- the
    same union+best-rank merge `EvidenceSet.add()` already does in production."""
    companies = rec.get("company") or []
    best: dict[int, int] = {}
    for co in companies:
        # the benchmark dataset's question already names the metric in text (e.g.
        # "Compare X and Y on revenue from operations.") -- reuse it as-is per company
        # rather than trying to re-derive a canonical metric name from the record.
        sub_q = rec["question"]
        cid = _company_id(repos, [co])
        filters = {"company_id": cid} if cid else None
        lexical_query = expand_lexical_query(sub_q) if query_expansion else None
        hits = retriever.retrieve(sub_q, k=max(_KS), candidate_k=40, mode=mode,
                                  filters=filters, rerank=rerank, intent=intent,
                                  lexical_query=lexical_query)
        for h in hits:
            if h.chunk.chunk_id not in best or h.rank < best[h.chunk.chunk_id]:
                best[h.chunk.chunk_id] = h.rank
    return sorted(best.items(), key=lambda kv: kv[1])


def run_mode(retriever, repos, records: list[dict], mode: str, *,
            filter_company: bool = True, rerank: bool = False,
            section_aware: bool = False, section_hints: bool = False,
            query_expansion: bool = False, multi_query: bool = False) -> dict[str, Any]:
    """`section_hints=True` (§10) additionally FILTERS candidates to the sections
    `finqa_v2.retrieval.section_weights.list_weighted_sections(intent)` names for the
    case's intent -- a harder constraint than `section_aware`'s soft re-ranking weight,
    and only meaningful combined with it (a case whose intent has no configured hints
    gets no filter either way)."""
    if mode not in retriever.modes:
        return {"skipped": f"mode '{mode}' unavailable (modes={retriever.modes})"}
    first_ranks: list[int | None] = []
    ndcg_rels: list[list[int]] = []
    lat: list[float] = []
    spurious_hits = 0
    n_no_gold = 0
    per_case = []
    for rec in records:
        gold = set(rec["gold_chunks"])
        cid = _company_id(repos, rec.get("company")) if filter_company else None
        filters: dict[str, Any] = {}
        if cid:
            filters["company_id"] = cid
        if section_hints:
            hints = list_weighted_sections(rec["intent"])
            if hints:
                filters["section"] = hints
        filters = filters or None
        intent = rec["intent"] if section_aware else None
        lexical_query = expand_lexical_query(rec["question"]) if query_expansion else None
        t0 = time.perf_counter()
        if multi_query and len(rec.get("company") or []) >= 2:
            merged = _multi_query_hits(retriever, repos, rec, mode=mode, rerank=rerank,
                                       intent=intent, query_expansion=query_expansion)
            chunk_ids = [cid_ for cid_, _ in merged][:max(_KS)]
        else:
            hits = retriever.retrieve(rec["question"], k=max(_KS), candidate_k=40,
                                      mode=mode, filters=filters, rerank=rerank, intent=intent,
                                      lexical_query=lexical_query)
            chunk_ids = [h.chunk.chunk_id for h in hits]
        lat.append((time.perf_counter() - t0) * 1000)
        rels = [1 if cid_ in gold else 0 for cid_ in chunk_ids]
        first = next((i + 1 for i, r in enumerate(rels) if r), None)
        if gold:
            first_ranks.append(first)
            ndcg_rels.append(rels)
        else:
            n_no_gold += 1
            if chunk_ids:
                spurious_hits += 1
        per_case.append({"id": rec["id"], "intent": rec["intent"],
                         "first_relevant_rank": first, "gold_size": len(gold)})
    lat_sorted = sorted(lat)
    return {
        "mode": mode, "n_total": len(records), "n_scored": len(first_ranks),
        **{f"recall@{k}": round(mean_recall_at_k(first_ranks, k), 4) for k in _KS},
        "mrr": round(mean_reciprocal_rank(first_ranks), 4),
        "ndcg@5": round(mean_ndcg_at_k(ndcg_rels, 5), 4),
        "p50_ms": round(statistics.median(lat), 2) if lat else None,
        "p95_ms": round(lat_sorted[int(0.95 * (len(lat_sorted) - 1))], 2) if lat else None,
        "no_gold_cases": n_no_gold,
        "spurious_hit_rate": round(spurious_hits / n_no_gold, 4) if n_no_gold else None,
        "per_case": per_case,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--bm25", type=Path, default=_BM25)
    ap.add_argument("--vector-dir", type=Path, default=_VEC)
    ap.add_argument("--modes", default="vector,lexical,hybrid")
    ap.add_argument("--filter-company", action="store_true", default=True)
    ap.add_argument("--no-filter-company", dest="filter_company", action="store_false")
    ap.add_argument("--rerank", action="store_true", help="wire the real CrossEncoderReranker")
    ap.add_argument("--section-aware", action="store_true",
                    help="pass each case's own intent to retrieve() for §15 section weighting")
    ap.add_argument("--section-hints", action="store_true",
                    help="§10: additionally FILTER to list_weighted_sections(intent), not just weight")
    ap.add_argument("--query-expansion", action="store_true",
                    help="§11/§12: expand the BM25 leg's query with financial-terminology synonyms")
    ap.add_argument("--multi-query", action="store_true",
                    help="§8/§9: for multi-company records, retrieve once per company and merge")
    ap.add_argument("--out", type=Path, default=None, help="write a JSON report here")
    ap.add_argument("--label", default="retrieval_v21_baseline")
    args = ap.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")

    records = load_dataset(args.dataset)
    repos = SqliteRepositories(args.v2_db)
    try:
        retriever = build_retriever(repos, bm25_path=args.bm25, vector_dir=args.vector_dir,
                                    use_reranker=args.rerank)
        results = {}
        for mode in (m.strip() for m in args.modes.split(",")):
            results[mode] = run_mode(retriever, repos, records, mode,
                                     filter_company=args.filter_company, rerank=args.rerank,
                                     section_aware=args.section_aware,
                                     section_hints=args.section_hints,
                                     query_expansion=args.query_expansion,
                                     multi_query=args.multi_query)
    finally:
        repos.close()

    print(f"dataset={args.dataset.name}  cases={len(records)}  retriever.modes={retriever.modes}")
    print()
    for mode, m in results.items():
        label = _MODE_LABEL.get(mode, mode)
        if "skipped" in m:
            print(f"{label}: skipped -- {m['skipped']}\n")
            continue
        print(f"{label}:")
        print(f"Recall@5 = {m['recall@5']}")
        print(f"MRR      = {m['mrr']}")
        print()

    print("full metrics:")
    header = f"{'mode':8s} " + " ".join(f"R@{k:<4}" for k in _KS) + "   MRR    nDCG@5  P50ms   P95ms  spurious"
    print(header)
    for mode, m in results.items():
        if "skipped" in m:
            print(f"{mode:8s} skipped")
            continue
        rvals = " ".join(f"{m[f'recall@{k}']:<6}" for k in _KS)
        print(f"{mode:8s} {rvals} {m['mrr']:<6} {m['ndcg@5']:<7} {m['p50_ms']:<7} {m['p95_ms']:<7} "
              f"{m['spurious_hit_rate']}")

    if args.out is not None:
        report = {
            "experiment_id": args.label, "git_commit": _git_commit(),
            "dataset": str(args.dataset), "n_cases": len(records),
            "retriever_modes_available": list(retriever.modes),
            "filter_company": args.filter_company, "rerank": args.rerank,
            "section_aware": args.section_aware, "section_hints": args.section_hints,
            "query_expansion": args.query_expansion, "multi_query": args.multi_query,
            "results": {mode: {k: v for k, v in m.items() if k != "per_case"} for mode, m in results.items()},
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
