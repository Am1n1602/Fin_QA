"""One-command rebuild of finqa_v2.db (§15). Runs the backfills in order, then the
coverage audit. Each step is idempotent, so re-running is safe / resumable.

    python -m finqa_v2.dataset.build [--v2-db PATH] [--skip-docs] [--no-tables]
        [--company TCS] [--from STEP]      # STEP in: import facts segments prices docs audit

Steps
  import    companies / indices / memberships / provenance   (finqa_v2.import_from_v1)
  facts     canonical XBRL -> financial_facts                (finqa_v2.normalize.backfill)
  segments  reportable-segment revenue                       (finqa_v2.normalize.backfill_segments)
  prices    EOD share prices -> share_prices                 (finqa_v2.prices.import_prices)
  docs      results PDFs -> document_chunks                  (finqa_v2.documents.backfill)  [slow]
  audit     coverage report                                  (finqa_v2.dataset.audit)
"""
from __future__ import annotations

import argparse
from pathlib import Path

from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_STEPS = ("import", "facts", "segments", "prices", "docs", "audit")


def build(v2_db: Path = DEFAULT_V2_DB_PATH, *, from_step: str = "import", skip_docs: bool = False,
          detect_tables: bool = True, company: str | None = None) -> dict:
    start = _STEPS.index(from_step)
    plan = [s for s in _STEPS[start:] if not (s == "docs" and skip_docs)]
    results: dict[str, dict] = {}

    for step in plan:
        print(f"\n=== {step} ===")
        if step == "import":
            from finqa_v2.import_from_v1 import run_import

            results["import"] = run_import(v2_db=v2_db)
        elif step == "facts":
            from finqa_v2.normalize.backfill import run_backfill as facts_backfill

            with SqliteRepositories(v2_db) as r:
                results["facts"] = facts_backfill(r, company=company)
            print(f"  {results['facts']['processed']}/{results['facts']['files']} files, "
                  f"{results['facts']['facts']} facts")
        elif step == "segments":
            from finqa_v2.normalize.backfill_segments import run_backfill as seg_backfill

            with SqliteRepositories(v2_db) as r:
                results["segments"] = seg_backfill(r, company=company)
        elif step == "prices":
            from finqa_v2.prices.import_prices import import_prices_dir

            with SqliteRepositories(v2_db) as r:
                results["prices"] = import_prices_dir(r, company=company)
            print(f"  {results['prices']['prices']} price rows")
        elif step == "docs":
            from finqa_v2.documents.backfill import run_backfill as doc_backfill

            with SqliteRepositories(v2_db) as r:
                results["docs"] = doc_backfill(r, company=company, detect_tables=detect_tables)
        elif step == "audit":
            from finqa_v2.dataset.audit import _print, audit_coverage

            with SqliteRepositories(v2_db) as r:
                report = audit_coverage(r)
            results["audit"] = report
            _print(report)

    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--from", dest="from_step", choices=_STEPS, default="import")
    ap.add_argument("--skip-docs", action="store_true", help="skip the slow PDF ingest step")
    ap.add_argument("--no-tables", action="store_true", help="docs: skip PyMuPDF table detection")
    ap.add_argument("--company", help="limit facts/segments/prices/docs to one ticker")
    args = ap.parse_args(argv)

    res = build(args.v2_db, from_step=args.from_step, skip_docs=args.skip_docs,
                detect_tables=not args.no_tables, company=args.company)
    rep = res.get("audit")
    return 1 if (rep and rep.get("critical")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
