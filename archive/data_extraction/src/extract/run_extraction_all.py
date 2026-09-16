"""
data_extraction/src/extract/run_extraction_all.py


Usage:
    python -m src.extract.run_extraction_all
    python -m src.extract.run_extraction_all --raw-base "data/raw"
"""
import argparse
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from src.config import COMPANIES
from src.extract.run_extraction import run_for_company


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw-base", default=None,
                     help="Override the base raw-data directory (default: data/raw/<symbol> per company, "
                          "matching run_extraction.py's own default).")
    args = ap.parse_args()

    print(f"[run_extraction_all] Processing {len(COMPANIES)} company/companies...\n")
    succeeded, failed = [], []
    for company in COMPANIES:
        symbol = company["nse_symbol"]
        raw_dir = f"{args.raw_base}/{symbol}" if args.raw_base else None
        print(f"\n=== {company['name']} ({symbol}) ===")
        try:
            run_for_company(symbol, raw_dir)
            succeeded.append(symbol)
        except Exception as e:
            print(f"[run_extraction_all] FAILED for {symbol}: {e}")
            failed.append(symbol)

    print(f"\n[run_extraction_all] Done. {len(succeeded)}/{len(COMPANIES)} company/companies "
          f"processed without a top-level failure.")
    if failed:
        print(f"[run_extraction_all] Failed: {', '.join(failed)} -- see the per-company "
              f"output above for details. (Note: run_extraction.run_for_company() already "
              f"catches per-*file* parse/map errors internally and continues to the next "
              f"file -- a company only lands here if something outside that, e.g. a missing "
              f"raw directory, actually raised.)")


if __name__ == "__main__":
    main()