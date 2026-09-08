"""
build_demo_corpus.py -- builds a small, self-contained demo dataset
(SQLite DB + FAISS indices) from the existing full financial_intelligence.db
and rag/data/indices/, for the zero-cost demo deployment.

Run from the project root, with the project's venv active (needs faiss and
numpy -- both already project dependencies, nothing extra to install):

    python build_demo_corpus.py

Defaults to the roadmap's suggested 8 companies (TCS, INFY, HCLTECH,
RELIANCE, ICICIBANK, ITC, BHARTIARTL, LT) and the project's normal default
paths for the source DB/index. Override with flags -- see --help. Neither
the source financial_intelligence.db nor the source rag/data/indices/ is
modified -- both are read-only inputs; everything is written under
data/demo/.

What it does:
  1. Copies financial_intelligence.db to a new demo DB.
  2. Deletes every row belonging to a company NOT in the keep-list, from
     every table that has one (companies, filings, financial_facts,
     financial_metrics, share_prices, documents, document_chunks) --
     children before parents.
  3. Copies rag/data/indices/ to a new demo index dir, keeping only the
     per-company FAISS files for the kept companies (excluded companies'
     files are simply never copied -- no slicing needed, they're already
     separate files), and surgically removing the excluded companies'
     vectors from global.faiss. This works because FAISS ids and
     document_chunks.id are the same values 1:1 (see rag/src/indexing/
     faiss_index.py's DualFaissIndex.add()) and the index is a
     faiss.IndexIDMap, which supports remove_ids().
  4. Note: BM25/phrase-overlap search need no separate handling -- per
     rag/src/pipeline/retrieve.py, there's no persistent BM25 index in
     this project yet (that's a RAG v2 roadmap item); it's rebuilt fresh
     from document_chunks on every query, so trimming the DB automatically
     scopes it too.
  5. Regenerates the FAISS index dir's own manifest.json (the same shape
     DualFaissIndex.save() writes -- read by run_ingest.py's DB/index
     mismatch check) and writes a separate, human-readable
     data/demo/manifest.json describing the frozen dataset. 
  6. VACUUMs the demo DB so the file size actually shrinks after the
     deletes (SQLite doesn't reclaim space on DELETE by itself).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import faiss
import numpy as np

DEFAULT_COMPANIES = ["TCS", "INFY", "HCLTECH", "RELIANCE", "ICICIBANK", "ITC", "BHARTIARTL", "LT"]


def _chunk_ids_to_remove(conn: sqlite3.Connection, keep: list[str]) -> list[int]:
    placeholders = ",".join("?" for _ in keep)
    rows = conn.execute(
        f"SELECT dc.id FROM document_chunks dc "
        f"JOIN documents d ON dc.document_id = d.id "
        f"WHERE d.company_symbol NOT IN ({placeholders})",
        keep,
    ).fetchall()
    return [r[0] for r in rows]


def _trim_db(db_path: Path, keep: list[str]) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = OFF")  # deleting out of strict FK order below, deliberately
    placeholders = ",".join("?" for _ in keep)

    removed_chunk_ids = _chunk_ids_to_remove(conn, keep)

    conn.execute(
        f"DELETE FROM document_chunks WHERE document_id IN "
        f"(SELECT id FROM documents WHERE company_symbol NOT IN ({placeholders}))",
        keep,
    )
    conn.execute(f"DELETE FROM documents WHERE company_symbol NOT IN ({placeholders})", keep)

    conn.execute(
        f"DELETE FROM financial_facts WHERE filing_id IN "
        f"(SELECT id FROM filings WHERE company_symbol NOT IN ({placeholders}))",
        keep,
    )
    conn.execute(
        f"DELETE FROM financial_metrics WHERE filing_id IN "
        f"(SELECT id FROM filings WHERE company_symbol NOT IN ({placeholders}))",
        keep,
    )
    conn.execute(f"DELETE FROM filings WHERE company_symbol NOT IN ({placeholders})", keep)
    conn.execute(f"DELETE FROM share_prices WHERE company_symbol NOT IN ({placeholders})", keep)
    conn.execute(f"DELETE FROM companies WHERE symbol NOT IN ({placeholders})", keep)

    conn.commit()
    conn.execute("VACUUM")

    counts = {
        "companies": conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0],
        "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "document_chunks": conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0],
        "filings": conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0],
    }
    conn.close()
    return {"removed_chunk_ids": removed_chunk_ids, "counts": counts}


def _trim_faiss(index_dir: Path, out_dir: Path, keep: list[str], removed_chunk_ids: list[int]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    company_counts: dict[str, int] = {}
    for sym in keep:
        src = index_dir / f"company_{sym.upper()}.faiss"
        if not src.exists():
            print(f"  [warn] no company_{sym.upper()}.faiss in {index_dir} -- skipping "
                  f"(that company may have no ingested filings yet)")
            continue
        dst = out_dir / src.name
        shutil.copy2(src, dst)
        idx = faiss.read_index(str(dst))
        company_counts[sym.upper()] = int(idx.ntotal)

    global_src = index_dir / "global.faiss"
    global_index = faiss.read_index(str(global_src))
    if removed_chunk_ids:
        n_removed = global_index.remove_ids(np.array(removed_chunk_ids, dtype=np.int64))
        print(f"  Removed {n_removed} vector(s) from global.faiss "
              f"({len(removed_chunk_ids)} chunk ids targeted).")
    faiss.write_index(global_index, str(out_dir / "global.faiss"))

    manifest = {
        "dim": global_index.d,
        "companies": company_counts,
        "global_total": int(global_index.ntotal),
    }
    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--companies", default=",".join(DEFAULT_COMPANIES),
                     help=f"Comma-separated symbols to KEEP. Default: {','.join(DEFAULT_COMPANIES)}")
    ap.add_argument("--db-path", default="database/data/financial_intelligence.db",
                     help="Source (full) database. Read-only -- never modified.")
    ap.add_argument("--index-dir", default="rag/data/indices",
                     help="Source (full) FAISS index dir. Read-only -- never modified.")
    ap.add_argument("--out-db", default="data/demo/finqa.db")
    ap.add_argument("--out-index-dir", default="data/demo/faiss")
    ap.add_argument("--manifest-out", default="data/demo/manifest.json",
                     help="Human-readable dataset manifest (roadmap section 13) -- separate "
                          "from the FAISS index dir's own manifest.json written alongside "
                          "--out-index-dir.")
    args = ap.parse_args()

    keep = [s.strip().upper() for s in args.companies.split(",") if s.strip()]
    src_db = Path(args.db_path)
    src_index_dir = Path(args.index_dir)
    out_db = Path(args.out_db)
    out_index_dir = Path(args.out_index_dir)

    if not src_db.exists():
        print(f"[ERROR] source DB not found: {src_db.resolve()}")
        return 1
    if not src_index_dir.exists():
        print(f"[ERROR] source index dir not found: {src_index_dir.resolve()}")
        return 1

    out_db.parent.mkdir(parents=True, exist_ok=True)
    print(f"Copying {src_db} -> {out_db} ...")
    shutil.copy2(src_db, out_db)

    print(f"Trimming demo DB to {len(keep)} companies: {', '.join(keep)}")
    trim_result = _trim_db(out_db, keep)
    print(f"  Kept: {trim_result['counts']}")
    print(f"  Chunk ids removed from FAISS: {len(trim_result['removed_chunk_ids'])}")

    print(f"Copying + trimming FAISS index: {src_index_dir} -> {out_index_dir} ...")
    faiss_manifest = _trim_faiss(src_index_dir, out_index_dir, keep, trim_result["removed_chunk_ids"])
    print(f"  {faiss_manifest}")

    dataset_manifest = {
        "version": "demo-v1",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "companies": keep,
        "documents": trim_result["counts"]["documents"],
        "document_chunks": trim_result["counts"]["document_chunks"],
        "embedding_model": "all-mpnet-base-v2",
        "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "database_version": "demo-v1",
    }
    Path(args.manifest_out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.manifest_out, "w") as f:
        json.dump(dataset_manifest, f, indent=2)
    print(f"\nWrote dataset manifest: {args.manifest_out}")

    print(f"\nDone. Demo dataset written to:\n  DB:    {out_db}\n  Index: {out_index_dir}")
    print(
        "\nThis script only BUILDS the demo dataset locally -- it doesn't deploy anything. "
        "To actually use it: copy/rename these on top of the paths the app expects "
        "(database/data/financial_intelligence.db and rag/data/indices/) in whatever image "
        "build context or upload you use for the demo host -- see Dockerfile and "
        "SESSION_ADDENDUM_25.md/26.md. Never overwrite your own real "
        "database/data/financial_intelligence.db with this -- build it to data/demo/ (the "
        "default) and only copy it into place inside the deploy artifact/build context."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())