"""
rag/src/pipeline/run_ingest.py

Production RAG ingestion driver: runs the full ingest_document() pipeline
(extraction -> chunking -> embedding -> DB -> dual FAISS index) against
every downloaded filing PDF recorded in data_extraction's
data/meta/{symbol}_filings.jsonl metadata index, across every company
found there.

Usage (run from rag/):
    # Real run, all companies, all documents, no cap
    python -m src.pipeline.run_ingest --meta-dir ../data_extraction/data/meta/

    # One company only
    python -m src.pipeline.run_ingest --meta-dir ../data_extraction/data/meta/ --symbol TCS

    # Mechanics-only dry run, no network needed
    python -m src.pipeline.run_ingest --meta-dir ../data_extraction/data/meta/ --mock --limit 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from src.storage.db import get_connection
from src.indexing.faiss_index import DualFaissIndex
from src.pipeline.ingest import ingest_document


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
    ap.add_argument("--symbol", default=None, help="Limit ingestion to one company symbol.")
    ap.add_argument("--source", default=None, help="Limit ingestion to one source (NSE/BSE).")
    ap.add_argument("--limit", type=int, default=None,
                     help="Cap the number of documents processed this run. Default: no cap "
                          "(process every not-yet-ingested document found).")
    ap.add_argument("--mock", action="store_true",
                     help="Use MockEmbedder (no network, no real semantics) instead of the real "
                          "model -- for mechanics-only dry runs, never for a real ingest.")
    ap.add_argument("--model-name", default="all-mpnet-base-v2")
    ap.add_argument("--device", default="auto",
                     help="'auto' (detect GPU if available), 'cuda', or 'cpu'")
    ap.add_argument("--batch-size", type=int, default=None,
                     help="Embedding batch size. Default: 16 when the resolved device is a GPU "
                          "(sized for typical laptop-GPU VRAM, not a datacenter card -- raise it "
                          "explicitly if your GPU has headroom), 32 on CPU. Pass a value to "
                          "override either default.")
    args = ap.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[ERROR] DB not found at {db_path.resolve()}. Run migrate.py against your "
              f"existing financial_intelligence.db first:\n"
              f"    python -m src.storage.migrate --db-path {args.db_path}")
        return 1

    meta_dir = Path(args.meta_dir)
    if not meta_dir.exists():
        print(f"[ERROR] meta-dir not found: {meta_dir.resolve()}")
        return 1

    if args.mock:
        from src.embedding.embedder import MockEmbedder
        print("[WARNING] Using MockEmbedder -- vectors are random, NOT semantically meaningful. "
              "Only appropriate for a mechanics-only dry run, never a real ingest.")
        embedder = MockEmbedder()
    else:
        from src.embedding.embedder import Embedder
        print(f"Loading real embedding model '{args.model_name}' "
              f"(downloads on first run, needs network access)...")
        embedder = Embedder(args.model_name, device=args.device)
        print(f"Model loaded, dim={embedder.dim}")

    if args.batch_size is not None:
        batch_size = args.batch_size
    else:
        # GPU default is deliberately conservative (16, not the 64-128
        # that's fine on a datacenter card) -- sized for a typical laptop
        # GPU's VRAM.
        batch_size = 16 if getattr(embedder, "device", None) == "cuda" else 32
    print(f"Using batch_size={batch_size} (device={getattr(embedder, 'device', 'n/a')})")

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
        return 1

    all_records: list[dict] = []
    for jf in jsonl_files:
        all_records.extend(load_jsonl(jf))

    if args.source:
        all_records = [r for r in all_records if str(r.get("source", "")).upper() == args.source.upper()]
    pdf_records = [r for r in all_records if str(r.get("local_path", "")).lower().endswith((".pdf", ".bin"))]
    targets = pdf_records[: args.limit] if args.limit is not None else pdf_records

    print(f"Ingesting {len(targets)} document(s) across {len(jsonl_files)} compan{'y' if len(jsonl_files) == 1 else 'ies'}...\n")

    status_counts = Counter()
    error_details: list[dict] = []
    with get_connection(str(db_path)) as conn:
        for i, rec in enumerate(targets):
            company = rec.get("company", "UNKNOWN")
            title = rec.get("title", "(no title)")
            doc_start = time.time()
            try:
                result = ingest_document(
                    conn, index, embedder,
                    company=company, title=title,
                    local_path=rec.get("local_path"), sha256=rec.get("sha256"),
                    source=rec.get("source"), period=rec.get("period"),
                    also_known_as=rec.get("also_known_as"),
                    batch_size=batch_size,
                )
            except Exception as e:
                result = {"status": "unexpected_error", "error": str(e)}
                error_details.append({"company": company, "title": title, "error": str(e)})
                print(f"  [{i + 1}/{len(targets)}] [{company}] {title[:55]:55s} -> "
                      f"unexpected_error: {e}")
                print("    " + traceback.format_exc().replace("\n", "\n    ").rstrip())

            elapsed = time.time() - doc_start
            status_counts[result["status"]] += 1
            if result["status"] != "unexpected_error":
                print(f"  [{i + 1}/{len(targets)}] [{company}] {title[:55]:55s} -> {result['status']}"
                      + (f" ({result.get('chunk_count')} chunks, {elapsed:.1f}s)" if "chunk_count" in result else "")
                      + (f" [{result.get('error')}]" if "error" in result else ""))

            if result["status"] == "ingested":
                index.save()

        print(f"\n=== Summary: {dict(status_counts)} ===")
        print(f"Indices saved to {Path(args.index_dir).resolve()}")
        if error_details:
            print(f"\n{len(error_details)} document(s) hit an unexpected error and were skipped:")
            for e in error_details:
                print(f"  [{e['company']}] {e['title'][:60]}: {e['error']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())