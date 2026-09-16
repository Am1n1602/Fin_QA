"""Build the small, curated dataset baked into the public demo image (see
deployment/docker/api.public.Dockerfile + deployment/README.md's "Public demo (Render)"
section). Copies rows straight out of the real, gitignored database/data/finqa_v2.db --
run this LOCALLY (never in CI/the image build), then rebuild+push the public image.

WHY a curated subset, not the full 50-company dataset: a first pass baked in the full
finqa_v2.db + finqa_v2_bm25.pkl (lexical-only, no vector index -- see the Dockerfile's own
comment on why no torch is loaded). That measured at ~680MB resident memory in a running
container -- almost all of it rank_bm25's BM25Okapi per-document term-frequency dicts for
the full 32,224-chunk corpus, comfortably over a typical free-tier's ~512MB ceiling. Since
that structure scales with chunk count, this script rebuilds a fresh, much smaller BM25
index from only the curated companies' chunks instead of shipping (and loading) the full
corpus. Measured after this change: see the README section for the current number --
always re-measure after changing TICKERS, don't assume.

    python deployment/scripts/build_public_dataset.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SRC_DB = ROOT / "database" / "data" / "finqa_v2.db"

OUT_DIR = ROOT / "deployment" / "docker" / "public_data"
OUT_DB = OUT_DIR / "finqa_v2.db"
OUT_BM25 = OUT_DIR / "finqa_v2_bm25.pkl"

# 12 companies (not all 50 -- see the module docstring), picked for sector diversity
# (IT/energy/banking/FMCG/auto/insurance) and to make sure every example question in the
# README and the dashboard's own QA/Research example chips actually resolves against this
# dataset -- including README's "Compare RELIANCE and ONGC on leverage", which needs ONGC
# specifically. SBILIFE also showcases the consolidated/standalone basis toggle (insurers
# file standalone only).
TICKERS = [
    "TCS", "INFY", "HCLTECH", "WIPRO",       # IT services
    "RELIANCE", "ONGC",                       # energy / conglomerate
    "HDFCBANK", "ICICIBANK", "SBIN",          # banks
    "ITC",                                    # FMCG
    "M&M",                                    # auto
    "SBILIFE",                                # insurance (standalone-only basis)
]

_COPY_TABLES = (
    ("companies", "company_id"),
    ("company_aliases", "company_id"),
    ("sources", "company_id"),
    ("financial_facts", "company_id"),
    ("segments", "company_id"),
    ("segment_facts", "company_id"),
    ("share_prices", "company_id"),
    ("documents", "company_id"),
    ("document_chunks", "company_id"),
)


def build_db() -> dict[str, int]:
    if not SRC_DB.exists():
        raise SystemExit(
            f"real dataset not found: {SRC_DB} -- this script copies FROM the full local "
            "dataset; build it first with `python -m finqa_v2.dataset.build`."
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DB.unlink(missing_ok=True)

    from finqa_v2.sqlite.repo import connect, init_db

    conn = connect(OUT_DB)
    init_db(conn)
    conn.execute("PRAGMA foreign_keys = OFF")  # re-checked explicitly below, after the copy
    conn.execute("ATTACH DATABASE ? AS src", (str(SRC_DB),))

    placeholders = ",".join("?" * len(TICKERS))
    company_ids = [r[0] for r in conn.execute(
        f"SELECT company_id FROM src.companies WHERE ticker IN ({placeholders})", TICKERS
    ).fetchall()]
    if len(company_ids) != len(TICKERS):
        raise SystemExit(f"expected {len(TICKERS)} companies in {SRC_DB}, found {len(company_ids)}")
    ids_sql = ",".join(str(i) for i in company_ids)

    index_ids = [r[0] for r in conn.execute(
        f"SELECT DISTINCT index_id FROM src.index_memberships WHERE company_id IN ({ids_sql})"
    ).fetchall()]
    if index_ids:
        conn.execute(f"INSERT INTO indices SELECT * FROM src.indices "
                     f"WHERE index_id IN ({','.join(str(i) for i in index_ids)})")
        conn.execute(f"INSERT INTO index_memberships SELECT * FROM src.index_memberships "
                     f"WHERE company_id IN ({ids_sql})")

    for table, id_col in _COPY_TABLES:
        conn.execute(f"INSERT INTO {table} SELECT * FROM src.{table} WHERE {id_col} IN ({ids_sql})")

    conn.commit()
    conn.execute("DETACH DATABASE src")

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise SystemExit(f"public dataset has dangling foreign keys, not writing it: {violations}")

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t, _ in _COPY_TABLES}
    conn.close()
    print(f"wrote {OUT_DB} ({OUT_DB.stat().st_size / 1024:.0f} KB): {counts}")
    return counts


def build_bm25() -> int:
    from finqa_v2.retrieval.lexical import BM25Index
    from finqa_v2.sqlite import SqliteRepositories

    repos = SqliteRepositories(OUT_DB)
    try:
        idx = BM25Index.build(repos)
        idx.save(OUT_BM25)
    finally:
        repos.close()
    print(f"wrote {OUT_BM25} ({OUT_BM25.stat().st_size / 1024:.0f} KB): {len(idx)} chunks")
    return len(idx)


def main() -> None:
    build_db()
    build_bm25()


if __name__ == "__main__":
    main()
