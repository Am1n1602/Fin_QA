"""Footprint measurement (§43): storage, index sizes, entity counts for the current
finqa_v2.db / retrieval indexes. Read-only.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DB = _ROOT / "database" / "data" / "finqa_v2.db"
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC = _ROOT / "database" / "data" / "finqa_v2_vec"

_TABLES = ("companies", "company_aliases", "indices", "index_memberships", "sources",
           "financial_facts", "segments", "segment_facts", "share_prices",
           "documents", "document_chunks")


def _bytes(p: Path) -> int:
    if not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def measure_footprint(repos, *, db_path: Path = _DB) -> dict:
    conn = repos.connection
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES}

    n_companies = counts["companies"] or 1
    n_index_members = conn.execute(
        "SELECT COUNT(*) FROM index_memberships WHERE valid_to IS NULL").fetchone()[0] or n_companies

    chunk_text_bytes = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(text)), 0) FROM document_chunks").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]

    storage = {
        "db_bytes": page_count * page_size,
        "db_bytes_on_disk": _bytes(db_path),
        "chunk_text_bytes": chunk_text_bytes,
        "bm25_index_bytes": _bytes(_BM25),
        "vector_index_bytes": _bytes(_VEC),
    }
    per_company = {
        "facts": counts["financial_facts"] / n_companies,
        "segment_facts": counts["segment_facts"] / n_companies,
        "share_prices": counts["share_prices"] / n_companies,
        "documents": counts["documents"] / n_companies,
        "chunks": counts["document_chunks"] / n_companies,
        "sources": counts["sources"] / n_companies,
        "db_bytes": storage["db_bytes"] / n_companies,
        "bm25_index_bytes": storage["bm25_index_bytes"] / n_companies,
        "vector_index_bytes": storage["vector_index_bytes"] / n_companies,
    }
    return {
        "companies": n_companies,
        "index_members": n_index_members,
        "counts": counts,
        "storage_bytes": storage,
        "per_company": {k: round(v, 1) for k, v in per_company.items()},
    }


def render(fp: dict) -> str:
    s = fp["storage_bytes"]
    lines = [
        f"footprint @ {fp['companies']} companies ({fp['index_members']} current index members)",
        "  entity counts:",
    ]
    for t, n in fp["counts"].items():
        lines.append(f"    {t:22} {n:>12,}   ({fp['per_company'].get(t.replace('financial_', '').replace('document_', ''), '') or ''})")
    lines += [
        "  storage:",
        f"    sqlite db            {s['db_bytes'] / 1e6:>10.1f} MB   ({s['db_bytes'] / fp['companies'] / 1e6:.2f} MB/co)",
        f"    chunk text           {s['chunk_text_bytes'] / 1e6:>10.1f} MB",
        f"    bm25 index           {s['bm25_index_bytes'] / 1e6:>10.1f} MB   ({s['bm25_index_bytes'] / fp['companies'] / 1e6:.2f} MB/co)",
        f"    vector index         {s['vector_index_bytes'] / 1e6:>10.1f} MB   ({s['vector_index_bytes'] / fp['companies'] / 1e6:.2f} MB/co)",
    ]
    return "\n".join(lines)
