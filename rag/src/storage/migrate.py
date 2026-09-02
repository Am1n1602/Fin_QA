from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def apply_migration(db_path: Path):
    schema_path = Path(__file__).parent / "schema_additions.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql)
        conn.commit()
        # Confirm what actually exists now, rather than assuming success.
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('documents', 'document_chunks')"
        ).fetchall()
        print(f"Migration applied to {db_path}")
        print(f"Confirmed tables present: {[t[0] for t in tables]}")
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-path", default="../database/data/financial_intelligence.db",
                     help="Path to the existing shared SQLite DB")
    args = ap.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"[ERROR] DB not found at {db_path.resolve()}. "
              f"Pass --db-path pointing at your existing financial_intelligence.db.")
        return

    apply_migration(db_path)


if __name__ == "__main__":
    main()