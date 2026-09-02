"""
[TEST ONLY]
Runs the full ingest_document() pipeline (extraction -> chunking ->
embedding -> DB -> dual FAISS index) against real PDFs from
data/meta/{symbol}_filings.jsonl
Uses the REAL Embedder (downloads all-mpnet-base-v2 from huggingface.co on
first run, then caches it) by default. Pass --mock to use MockEmbedder
instead for a network-free dry run of the pipeline mechanics only -- NEVER
use --mock output for anything but checking the pipeline doesn't crash;
the vectors are semantically meaningless.

Usage (run from rag/):
    # First real run -- needs network access, downloads the model once
    python -m src.pipeline.run_ingest_test --meta-dir ..\\data_extraction\\data\\meta\\ --limit 10

    # Mechanics-only dry run, no network needed
    python -m src.pipeline.run_ingest_test --meta-dir ..\\data_extraction\\data\\meta\\ --limit 10 --mock

    # After ingesting, try an actual retrieval query
    python -m src.pipeline.run_ingest_test --meta-dir ..\\data_extraction\\data\\meta\\ --limit 30 --query "dividend declaration"
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from src.storage.db import get_connection
from src.indexing.faiss_index import DualFaissIndex
from src.pipeline.ingest import ingest_document
from src.pipeline.retrieve import retrieve, hybrid_retrieve, reranked_retrieve


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--meta-dir", default="../data_extraction/data/meta")
    ap.add_argument("--db-path", default="../database/data/financial_intelligence.db")
    ap.add_argument("--index-dir", default="data/indices")
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--mock", action="store_true",
                     help="Use MockEmbedder (no network, no real semantics) instead of the real model")
    ap.add_argument("--model-name", default="all-mpnet-base-v2")
    ap.add_argument("--device", default="auto",
                     help="'auto' (detect GPU if available), 'cuda', or 'cpu'")
    ap.add_argument("--batch-size", type=int, default=32,
                     help="Embedding batch size. Try 64-128 on GPU with enough VRAM for faster throughput.")
    ap.add_argument("--query", default=None, help="If given, run this retrieval query after ingesting")
    ap.add_argument("--query-company", default=None, help="Scope --query to one company; omit for global search")
    ap.add_argument("--k", type=int, default=5, help="Number of retrieval results to show")
    ap.add_argument("--rerank", choices=["cross_encoder", "hybrid", "none"], default="cross_encoder",
                     help="'cross_encoder' (default): hybrid candidate pool + cross-encoder rescoring, "
                          "the strongest option. 'hybrid': semantic + BM25 + phrase overlap only, no "
                          "reranking pass. 'none': pure semantic (FAISS only), for comparison.")
    ap.add_argument("--rerank-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    args = ap.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[ERROR] DB not found at {db_path.resolve()}. Run migrate.py against your "
              f"existing financial_intelligence.db first:\n"
              f"    python -m src.storage.migrate --db-path {args.db_path}")
        return

    meta_dir = Path(args.meta_dir)
    if not meta_dir.exists():
        print(f"[ERROR] meta-dir not found: {meta_dir.resolve()}")
        return

    if args.mock:
        from src.embedding.embedder import MockEmbedder
        print("[WARNING] Using MockEmbedder -- vectors are random, NOT semantically meaningful. "
              "Only useful for checking the pipeline runs without crashing.")
        embedder = MockEmbedder()
    else:
        from src.embedding.embedder import Embedder
        print(f"Loading real embedding model '{args.model_name}' "
              f"(downloads on first run, needs network access)...")
        embedder = Embedder(args.model_name, device=args.device)
        print(f"Model loaded, dim={embedder.dim}")

    reranker = None
    if args.query and args.rerank == "cross_encoder":
        if args.mock:
            from src.reranking.reranker import MockCrossEncoderReranker
            print("[WARNING] Using MockCrossEncoderReranker -- word-overlap only, NOT a real "
                  "cross-encoder signal.")
            reranker = MockCrossEncoderReranker()
        else:
            from src.reranking.reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker(args.rerank_model, device=args.device)

    index = DualFaissIndex(dim=embedder.dim, index_dir=args.index_dir)

    manifest_path = Path(args.index_dir) / "manifest.json"
    with get_connection(str(db_path)) as _check_conn:
        db_chunk_count = _check_conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    index_total = 0
    if manifest_path.exists():
        with open(manifest_path) as f:
            index_total = json.load(f).get("global_total", 0)
    if db_chunk_count > 0 and index_total < db_chunk_count:
        print("!" * 70)
        print("[WARNING] DB/INDEX MISMATCH DETECTED")
        print(f"  documents.document_chunks has {db_chunk_count} row(s), but the FAISS "
              f"index only has {index_total} vector(s).")
        print("  This almost always means data/indices/ was cleared without also "
              "clearing the DB tables (or vice versa).")
        print("  Every document already in the DB will be reported 'already_ingested' "
              "and SKIPPED -- their vectors will NOT be added, even though this run "
              "looks like it's working normally.")
        print("  Fix: run `python clear_rag_data.py` to reset both sides together, "
              "then re-run ingestion from scratch.")
        print("!" * 70)
        print()

    jsonl_files = sorted(meta_dir.glob("*_filings.jsonl"))
    if args.symbol:
        jsonl_files = [f for f in jsonl_files if f.name.upper().startswith(args.symbol.upper())]
    if not jsonl_files:
        print(f"[ERROR] No matching *_filings.jsonl files found in {meta_dir.resolve()}")
        return

    all_records: list[dict] = []
    for jf in jsonl_files:
        all_records.extend(load_jsonl(jf))

    if args.source:
        all_records = [r for r in all_records if str(r.get("source", "")).upper() == args.source.upper()]
    pdf_records = [r for r in all_records if str(r.get("local_path", "")).lower().endswith((".pdf", ".bin"))]
    targets = pdf_records[: args.limit]

    print(f"Ingesting {len(targets)} document(s)...\n")

    status_counts = Counter()
    with get_connection(str(db_path)) as conn:
        for i, rec in enumerate(targets):
            company = rec.get("company", "UNKNOWN")
            title = rec.get("title", "(no title)")
            doc_start = time.time()
            result = ingest_document(
                conn, index, embedder,
                company=company, title=title,
                local_path=rec.get("local_path"), sha256=rec.get("sha256"),
                source=rec.get("source"), period=rec.get("period"),
                also_known_as=rec.get("also_known_as"),
                batch_size=args.batch_size,
            )
            elapsed = time.time() - doc_start
            status_counts[result["status"]] += 1
            print(f"  [{i + 1}/{len(targets)}] [{company}] {title[:55]:55s} -> {result['status']}"
                  + (f" ({result.get('chunk_count')} chunks, {elapsed:.1f}s)" if "chunk_count" in result else "")
                  + (f" [{result.get('error')}]" if "error" in result else ""))

            if result["status"] == "ingested":
                index.save()

        print(f"\n=== Summary: {dict(status_counts)} ===")
        print(f"Indices saved to {Path(args.index_dir).resolve()}")

        if args.query:
            print(f"\n=== Retrieval test: \"{args.query}\" "
                  f"(company={args.query_company or 'ALL'}, rerank={args.rerank}) ===")
            if args.rerank == "cross_encoder":
                results = reranked_retrieve(conn, index, embedder, reranker, query=args.query,
                                             k=args.k, company=args.query_company)
            elif args.rerank == "hybrid":
                results = hybrid_retrieve(conn, index, embedder, query=args.query,
                                           k=args.k, company=args.query_company)
            else:
                results = retrieve(conn, index, embedder, query=args.query,
                                    k=args.k, company=args.query_company)
            if not results:
                print("  (no results)")
            for r in results:
                rerank_info = f" rerank_score={r['rerank_score']:.3f}" if "rerank_score" in r else ""
                print(f"  score={r['score']:.3f}{rerank_info} [{r['company']}] {r['title'][:50]} "
                      f"p{r['page_start']}-{r['page_end']} sec={r['section']}")
                print(f"    {r['text'][:150]}")


if __name__ == "__main__":
    main()