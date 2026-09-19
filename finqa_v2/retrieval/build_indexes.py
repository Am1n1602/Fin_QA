"""Build retrieval indexes from finqa_v2.db.document_chunks.

BM25 is always built (pure Python). --vector additionally builds the dense index
(needs sentence-transformers/torch); on failure it reports and exits 3 for that part
only, leaving the BM25 index in place.

    python -m finqa_v2.retrieval.build_indexes [--vector] [--v2-db PATH]
        [--bm25-out PATH] [--vector-dir PATH] [--model NAME] [--hash-embedder]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[2]
_BM25_OUT = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC_DIR = _ROOT / "database" / "data" / "finqa_v2_vec"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--bm25-out", type=Path, default=_BM25_OUT)
    ap.add_argument("--vector", action="store_true")
    ap.add_argument("--vector-dir", type=Path, default=_VEC_DIR)
    ap.add_argument("--model", default="all-mpnet-base-v2")
    ap.add_argument("--device", default="auto",
                    help="'auto' (cuda if available else cpu), 'cuda', or 'cpu'.")
    ap.add_argument("--hash-embedder", action="store_true",
                    help="Build the vector index with the dependency-free HashEmbedder "
                         "(exercises the path; not semantically strong).")
    ap.add_argument("--metadata-enriched", action="store_true",
                    help="Prepend a company/FY/section/page header to each chunk's text "
                         "before embedding (finqa_v2.retrieval.text_builder). Does not "
                         "change document_chunks.text; only the embedder's input.")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--trust-remote-code", action="store_true",
                    help="Needed for models that ship custom modeling code (e.g. "
                         "jina-embeddings-v3). Off by default -- executes remote code.")
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

        from finqa_v2.retrieval.embed import HashEmbedder, SentenceTransformerEmbedder
        from finqa_v2.retrieval.vector import VectorIndex

        device = args.device
        if device == "auto":
            try:
                import torch

                device = "cuda" if torch.cuda.is_available() else "cpu"
            except Exception:
                device = "cpu"
        if args.hash_embedder:
            embedder = HashEmbedder()
        else:
            embedder = SentenceTransformerEmbedder(args.model, device=device,
                                                   batch_size=args.batch_size,
                                                   trust_remote_code=args.trust_remote_code)
            print(f"[vector] embedding with {args.model} on {device}")
        text_fn = None
        if args.metadata_enriched:
            from finqa_v2.retrieval.text_builder import from_row

            text_fn = from_row
            print("[vector] embedding text is metadata-enriched (company/FY/section/page header)")
        try:
            idx = VectorIndex.build(repos, embedder, text_fn=text_fn)
        except Exception as e:  # torch/paging-file/import failures land here
            print(f"[vector] FAILED to build ({type(e).__name__}: {e}).")
            print("[vector] BM25 index is still in place; retry --vector when the model "
                  "environment is stable, or run with --hash-embedder.")
            return 3
        idx.save(args.vector_dir)
        model_id = "hash-embedder" if args.hash_embedder else args.model
        extra_lines = ""
        if args.metadata_enriched:
            extra_lines += "\nmetadata_enriched=1"
        if args.trust_remote_code:
            extra_lines += "\ntrust_remote_code=1"
        (args.vector_dir / "model.txt").write_text(f"{model_id}\ndevice={device}{extra_lines}\n",
                                                   encoding="utf-8")
        print(f"[vector] {len(idx.chunk_ids)} chunks, dim={idx.dim}, model={model_id}, "
              f"faiss={'yes' if idx._faiss is not None else 'numpy'} -> {args.vector_dir}")
        print("[vector] NOTE: query with the SAME embedder -- "
              f"HybridRetriever(..., embedder=SentenceTransformerEmbedder('{model_id}'))")
        return 0
    finally:
        repos.close()


if __name__ == "__main__":
    raise SystemExit(main())
