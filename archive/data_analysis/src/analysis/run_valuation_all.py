"""
Usage:
    python -m src.analysis.run_valuation_all

"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from src.analysis.combine_and_analyze_all import discover_pairs
from src.analysis.valuation import run_and_save
from src.config import EXTRACTED_DIR


def main():
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extracted-dir", default=None,
                     help="Override the directory to scan for *_canonical.json files.")
    args = ap.parse_args()

    extracted_dir = Path(args.extracted_dir) if args.extracted_dir else EXTRACTED_DIR
    pairs = discover_pairs(extracted_dir)
    print(f"[run_valuation_all] Found {len(pairs)} (company, filing_type) pair(s) to value.\n")

    succeeded, failed = [], []
    for company, filing_type in pairs:
        print(f"=== {company} ({filing_type}) ===")
        try:
            result = run_and_save(company, filing_type, verbose=False)
            pe = result["pe"]["pe_ratio"]
            pb = result["pb"]["pb_ratio"]
            close = result["pe"]["latest_close"]
            print(f"  -> latest_close={close}  pe_ratio={pe}  pb_ratio={pb}")
            succeeded.append((company, filing_type))
        except Exception as e:
            print(f"[run_valuation_all] FAILED for {company} ({filing_type}): {e}")
            failed.append((company, filing_type))
        print()

    print(f"[run_valuation_all] Done. {len(succeeded)}/{len(pairs)} pair(s) valued without error.")
    if failed:
        print(f"[run_valuation_all] Failed: {', '.join(f'{c}/{t}' for c, t in failed)}")
    print("\nNext: re-run database's load_data (python -m src.load_data from database/) "
          "to load these into the database.")


if __name__ == "__main__":
    main()