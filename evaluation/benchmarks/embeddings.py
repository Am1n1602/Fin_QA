"""Embedding-model benchmark (§7): all-MiniLM-L6-v2 (current) vs BAAI/bge-m3 vs
jinaai/jina-embeddings-v3 -- same corpus, same retrieval_v21 dataset (§7: "The benchmark
must use the same corpus and same retrieval dataset").

    python -m evaluation.benchmarks.embeddings [--dataset evaluation/datasets/retrieval_v21.json]
        [--json evaluation/results/embedding_models_v21.json]

This script does NOT build vector indexes itself -- that's a one-time, possibly-multi-GB
download, possibly slow-on-limited-VRAM operation better run explicitly and checked before
being trusted:

    python -m finqa_v2.retrieval.build_indexes --vector --model BAAI/bge-m3 --device cuda \\
        --batch-size 8 --vector-dir database/data/finqa_v2_vec_bge_m3

A candidate whose directory doesn't exist (build failed, or was never attempted) is
reported as "skipped", not silently excluded from the printed table.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from evaluation.run_retrieval_benchmark import load_dataset, run_mode
from finqa_v2.retrieval.evaluate import build_retriever
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATASET = _ROOT / "evaluation" / "datasets" / "retrieval_v21.json"
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"

# name -> vector index directory. "current" is what's actually shipped/wired in production.
CANDIDATES = {
    "all-MiniLM-L6-v2 (current)": _ROOT / "database" / "data" / "finqa_v2_vec",
    "BAAI/bge-m3": _ROOT / "database" / "data" / "finqa_v2_vec_bge_m3",
    "jinaai/jina-embeddings-v3": _ROOT / "database" / "data" / "finqa_v2_vec_jina_v3",
}


def _dir_size_mb(path: Path) -> float | None:
    if not path.exists():
        return None
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


def _sample_embed_latency_ms(embedder, repos, n: int = 20) -> float | None:
    """Per-chunk encode latency from a small real sample -- not a full corpus re-embed
    (that's what building the index already did; redoing it here would just be slow)."""
    rows = repos.connection.execute("SELECT text FROM document_chunks LIMIT ?", (n,)).fetchall()
    texts = [r[0] for r in rows]
    if not texts:
        return None
    t0 = time.perf_counter()
    embedder.encode(texts)
    return round((time.perf_counter() - t0) * 1000 / len(texts), 2)


def benchmark_model(name: str, vector_dir: Path, repos, records: list[dict]) -> dict:
    if not vector_dir.exists():
        return {"model": name, "skipped": f"vector index not built at {vector_dir}"}
    retriever = build_retriever(repos, bm25_path=_BM25, vector_dir=vector_dir)
    if "vector" not in retriever.modes:
        return {"model": name, "skipped": "vector mode unavailable (index failed to load)"}

    embed_latency_ms = _sample_embed_latency_ms(retriever._embedder, repos)
    retrieval = run_mode(retriever, repos, records, "vector", section_aware=True)
    return {
        "model": name,
        "index_size_mb": _dir_size_mb(vector_dir),
        "embed_latency_ms_per_chunk": embed_latency_ms,
        "query_p50_ms": retrieval.get("p50_ms"),
        "query_p95_ms": retrieval.get("p95_ms"),
        "recall@5": retrieval.get("recall@5"),
        "recall@10": retrieval.get("recall@10"),
        "mrr": retrieval.get("mrr"),
        "ndcg@5": retrieval.get("ndcg@5"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    records = load_dataset(args.dataset)
    repos = SqliteRepositories(args.v2_db)
    try:
        results = [benchmark_model(name, vector_dir, repos, records)
                  for name, vector_dir in CANDIDATES.items()]
    finally:
        repos.close()

    print(f"{'model':32s} {'idx MB':>8s} {'emb ms/chunk':>13s} {'q p50':>7s} {'q p95':>7s} "
          f"{'R@5':>6s} {'R@10':>6s} {'MRR':>6s} {'nDCG@5':>7s}")
    for r in results:
        if "skipped" in r:
            print(f"{r['model']:32s} -- skipped: {r['skipped']}")
            continue
        print(f"{r['model']:32s} {r['index_size_mb']!s:>8s} {r['embed_latency_ms_per_chunk']!s:>13s} "
              f"{r['query_p50_ms']!s:>7s} {r['query_p95_ms']!s:>7s} {r['recall@5']!s:>6s} "
              f"{r['recall@10']!s:>6s} {r['mrr']!s:>6s} {r['ndcg@5']!s:>7s}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"dataset": str(args.dataset), "results": results}, indent=2),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
