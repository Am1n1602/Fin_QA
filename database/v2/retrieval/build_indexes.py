"""Build retrieval indexes from finqa_v2.db.document_chunks.

BM25 is always built (pure Python). --vector additionally builds the dense index
(needs sentence-transformers/torch); on failure it reports and exits 3 for that part
only, leaving the BM25 index in place.

    python -m database.v2.retrieval.build_indexes [--vector] [--v2-db PATH]
        [--bm25-out PATH] [--vector-dir PATH] [--model NAME] [--hash-embedder]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from database.v2.retrieval.lexical import BM25Index
from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[3]
_BM25_OUT = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC_DIR = _ROOT / "database" / "data" / "finqa_v2_vec"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--bm25-out", type=Path, default=_BM25_OUT)
    ap.add_argument("--vector", action="store_true")
    ap.add_argument("--vector-dir", type=Path, default=_VEC_DIR)
    ap.add_argument("--model", default="all-mpnet-base-v2")
    ap.add_argument("--hash-embedder", action="store_true",
                    help="Build the vector index with the dependency-free HashEmbedder "
                         "(exercises the path; not semantically strong).")
    args = ap.parse_args()

    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db} -- run the Phase 1-5 backfills first")

    repos = SqliteRepositories(args.v2_db)
    try:
        bm25 = BM25Index.build(repos)
        bm25.save(args.bm25_out)
        print(f"[bm25] {len(bm25)} chunks -> {args.bm25_out}")

        if not args.vector:
            return 0

        from database.v2.retrieval.embed import HashEmbedder, SentenceTransformerEmbedder
        from database.v2.retrieval.vector import VectorIndex

        embedder = HashEmbedder() if args.hash_embedder else SentenceTransformerEmbedder(args.model)
        try:
            idx = VectorIndex.build(repos, embedder)
        except Exception as e:  # torch/paging-file/import failures land here
            print(f"[vector] FAILED to build ({type(e).__name__}: {e}).")
            print("[vector] BM25 index is still in place; retry --vector when the model "
                  "environment is stable, or run with --hash-embedder.")
            return 3
        idx.save(args.vector_dir)
        print(f"[vector] {len(idx.chunk_ids)} chunks, dim={idx.dim}, "
              f"faiss={'yes' if idx._faiss is not None else 'numpy'} -> {args.vector_dir}")
        return 0
    finally:
        repos.close()


if __name__ == "__main__":
    raise SystemExit(main())
