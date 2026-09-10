"""Copy a SQLite finqa_v2.db into PostgreSQL, primary keys preserved, then load the
dense embeddings from the faiss index dir into `document_chunks.embedding` (§17).

Idempotent: every table is TRUNCATEd then re-filled (the schema is applied first).

    FINQA_PG_URL=postgresql://finqa:finqa@localhost:55432/finqa \
      python -m finqa_v2.postgres.migrate [--sqlite PATH] [--vector-dir PATH] [--no-vectors]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finqa_v2.postgres.repo import PgRepositories, connect_pg, init_pg, _PgConn
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[2]
_VEC = _ROOT / "database" / "data" / "finqa_v2_vec"

# child-before-parent is wrong for insert; this is parent-first (FK-safe) order.
_TABLES = ("companies", "company_aliases", "indices", "index_memberships", "sources",
           "financial_facts", "segments", "segment_facts", "share_prices",
           "documents", "document_chunks")
_IDENTITY_PK = {
    "companies": "company_id", "indices": "index_id", "sources": "source_id",
    "financial_facts": "fact_id", "segments": "segment_id",
    "segment_facts": "segment_fact_id", "share_prices": "price_id",
    "documents": "document_id", "document_chunks": "chunk_id",
}


def _copy_table(src_conn, pg_raw, table: str) -> int:
    rows = src_conn.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        return 0
    cols = list(rows[0].keys())
    collist = ", ".join(cols)
    ph = ", ".join(["%s"] * len(cols))
    overriding = " OVERRIDING SYSTEM VALUE" if table in _IDENTITY_PK else ""
    with pg_raw.cursor() as cur:
        cur.execute(f"TRUNCATE {table} RESTART IDENTITY CASCADE")
        cur.executemany(
            f"INSERT INTO {table} ({collist}){overriding} VALUES ({ph})",
            [tuple(r[c] for c in cols) for r in rows],
        )
        if table in _IDENTITY_PK:
            pk = _IDENTITY_PK[table]
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{pk}'), "
                f"COALESCE((SELECT MAX({pk}) FROM {table}), 1))"
            )
    return len(rows)


def _load_vectors(pg_raw, vector_dir: Path) -> int:
    import numpy as np
    from pgvector.psycopg import register_vector

    matrix = np.load(vector_dir / "matrix.npy").astype("float32")
    ids = json.loads((vector_dir / "ids.json").read_text())
    register_vector(pg_raw)
    with pg_raw.cursor() as cur:
        cur.executemany(
            "UPDATE document_chunks SET embedding = %s WHERE chunk_id = %s",
            [(matrix[i], cid) for i, cid in enumerate(ids)],
        )
    return len(ids)


def migrate(sqlite_path: Path = DEFAULT_V2_DB_PATH, *, url: str | None = None,
            vector_dir: Path = _VEC, with_vectors: bool = True) -> dict:
    src = SqliteRepositories(sqlite_path)
    pg_raw = connect_pg(url)
    try:
        init_pg(_PgConn(pg_raw))
        counts = {t: _copy_table(src.connection, pg_raw, t) for t in _TABLES}
        pg_raw.commit()
        vectors = 0
        if with_vectors and (vector_dir / "matrix.npy").exists():
            vectors = _load_vectors(pg_raw, vector_dir)
            pg_raw.commit()
        return {"tables": counts, "vectors": vectors}
    finally:
        src.close()
        pg_raw.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--url")
    ap.add_argument("--vector-dir", type=Path, default=_VEC)
    ap.add_argument("--no-vectors", action="store_true")
    args = ap.parse_args(argv)

    res = migrate(args.sqlite, url=args.url, vector_dir=args.vector_dir,
                  with_vectors=not args.no_vectors)
    for t, n in res["tables"].items():
        print(f"  {t:22} {n:>10,}")
    print(f"  {'embeddings loaded':22} {res['vectors']:>10,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
