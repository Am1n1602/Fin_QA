
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

    # Children before parents (kept even with foreign_keys off, so this stays
    # correct if that pragma is ever removed later).
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

    # global.faiss holds every company's vectors together, so (unlike the
    # per-company files above) it can't just be selectively copied -- load
    # it, remove the excluded companies' vectors, save the trimmed result.
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
    ap.add_argument("--out-db", default="demo_dataset/finqa.db")
    ap.add_argument("--out-index-dir", default="demo_dataset/faiss")
    ap.add_argument("--manifest-out", default="demo_dataset/manifest.json",
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
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())