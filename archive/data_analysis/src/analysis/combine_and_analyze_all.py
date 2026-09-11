"""
data_analysis/src/analysis/combine_and_analyze_all.py

Loops combine_and_analyze.combine() across every (company, filing_type)
pair actually present in data_extraction's extracted canonical JSONs --
the data_analysis-step equivalent of run_extraction_all.py for
extraction and run_pipeline.py's main() for fetch.

Usage:
    python -m src.analysis.combine_and_analyze_all
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

from src.analysis.combine_and_analyze import combine
from src.analysis.ratios import format_ratio_value
from src.config import EXTRACTED_DIR, ANALYSIS_OUTPUT_DIR

_PATTERN = re.compile(r"^(.+)_(consolidated|standalone)_.+_canonical\.json$")


def discover_pairs(extracted_dir: Path = EXTRACTED_DIR) -> list[tuple[str, str]]:
    """Every distinct (company, filing_type) combination with at least
    one canonical JSON file on disk, sorted for deterministic output."""
    pairs: set[tuple[str, str]] = set()
    for path in sorted(Path(extracted_dir).glob("*_canonical.json")):
        m = _PATTERN.match(path.name)
        if not m:
            print(f"[combine_and_analyze_all] Skipping unrecognized filename: {path.name}")
            continue
        pairs.add((m.group(1), m.group(2)))
    return sorted(pairs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--extracted-dir", default=None,
                     help="Override the directory to scan for *_canonical.json files.")
    args = ap.parse_args()

    extracted_dir = Path(args.extracted_dir) if args.extracted_dir else EXTRACTED_DIR
    pairs = discover_pairs(extracted_dir)
    print(f"[combine_and_analyze_all] Found {len(pairs)} (company, filing_type) pair(s) to analyze.\n")

    succeeded, failed = [], []
    for company, filing_type in pairs:
        print(f"=== {company} ({filing_type}) ===")
        try:
            result = combine(company, filing_type, extracted_dir)
            out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_combined_ratios.json"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(result, indent=2, default=str))
            print(f"  -> {len(result['periods'])} period(s), {len(result['trends'])} trend(s) -- saved to {out_path.name}")
            succeeded.append((company, filing_type))
        except Exception as e:
            print(f"[combine_and_analyze_all] FAILED for {company} ({filing_type}): {e}")
            failed.append((company, filing_type))
        print()

    print(f"[combine_and_analyze_all] Done. {len(succeeded)}/{len(pairs)} pair(s) analyzed without error.")
    if failed:
        print(f"[combine_and_analyze_all] Failed: {', '.join(f'{c}/{t}' for c, t in failed)}")


if __name__ == "__main__":
    main()