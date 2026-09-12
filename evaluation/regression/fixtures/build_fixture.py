"""Build the small committed SQLite fixture (6 companies, no documents/chunks) that CI's
regression gate diffs against -- see evaluation/regression/README.md. Copies rows straight
out of the real, gitignored database/data/finqa_v2.db; run this LOCALLY (never in CI) after
the dataset changes in a way that should be reflected in the fixture, then re-pin the
baseline with evaluation.runners.v2_runner + evaluation.regression.compare --update.

    python -m evaluation.regression.fixtures.build_fixture
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC_DB = ROOT / "database" / "data" / "finqa_v2.db"
FULL_DATASET = ROOT / "evaluation" / "datasets" / "finqa_v2_eval.jsonl"

FIXTURE_DIR = Path(__file__).parent
FIXTURE_DB = FIXTURE_DIR / "finqa_v2_fixture.db"
FIXTURE_DATASET = FIXTURE_DIR / "finqa_v2_eval_fixture.jsonl"

# Chosen for category + engine-path coverage, not just size: two IT-services peers (TCS,
# INFY) for comparison questions, a segment-heavy conglomerate (RELIANCE), a third IT
# company (HCLTECH) that the causal/why fixtures in the source dataset target, and two
# banks (HDFCBANK, ICICIBANK) since bank ratios take a different engine path (no revenue
# line) than the others.
TICKERS = ["TCS", "INFY", "RELIANCE", "HCLTECH", "HDFCBANK", "ICICIBANK"]

_COPY_TABLES = (
    ("companies", "company_id"),
    ("company_aliases", "company_id"),
    ("sources", "company_id"),
    ("financial_facts", "company_id"),
    ("segments", "company_id"),
    ("segment_facts", "company_id"),
    ("share_prices", "company_id"),
)


def build_db() -> dict[str, int]:
    if not SRC_DB.exists():
        raise SystemExit(
            f"real dataset not found: {SRC_DB} -- this script copies FROM the full local "
            "dataset; build it first with `python -m finqa_v2.dataset.build`."
        )
    FIXTURE_DB.unlink(missing_ok=True)

    from finqa_v2.sqlite.repo import connect, init_db

    conn = connect(FIXTURE_DB)
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
        raise SystemExit(f"fixture has dangling foreign keys, not committing it: {violations}")

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t, _ in _COPY_TABLES}
    conn.close()
    print(f"wrote {FIXTURE_DB} ({FIXTURE_DB.stat().st_size / 1024:.0f} KB): {counts}")
    return counts


def build_dataset() -> int:
    chosen = set(TICKERS)
    kept = []
    with FULL_DATASET.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            companies = set(rec.get("companies") or [])
            if not companies or companies <= chosen:
                kept.append(rec)
    with FIXTURE_DATASET.open("w", encoding="utf-8") as f:
        for rec in kept:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {FIXTURE_DATASET}: {len(kept)}/{sum(1 for _ in FULL_DATASET.open(encoding='utf-8'))} records")
    return len(kept)


def main() -> None:
    build_db()
    build_dataset()


if __name__ == "__main__":
    main()
