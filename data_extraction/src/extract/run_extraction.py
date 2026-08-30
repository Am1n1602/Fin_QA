"""
Runs extraction (xbrl_lite_parser) + mapping (schema) for EVERY .xbrl file
found under data/raw/{company}/, in one command — replaces manually
running two commands per quarter per filing-type.
Usage:
    python -m src.extract.run_extraction TCS
    python -m src.extract.run_extraction TCS --raw-dir "data/raw/TCS"
"""
import sys
from pathlib import Path

from src.extract.xbrl_lite_parser import parse_and_save
from src.extract.schema import map_and_save


def run_for_company(company: str, raw_dir: str | None = None) -> None:
    raw_path = Path(raw_dir) if raw_dir else Path("data/raw") / company
    xbrl_files = sorted(raw_path.glob("*.xbrl")) + sorted(raw_path.glob("*.xml"))
    if not xbrl_files:
        print(f"[run_extraction] No .xbrl/.xml files found under {raw_path}/ "
              f"— check the company symbol matches your data/raw/ folder name.")
        return

    print(f"[run_extraction] Found {len(xbrl_files)} XBRL file(s) for {company} under {raw_path}/\n")

    results = []
    for f in xbrl_files:
        print(f"--- {f.name} ---")
        try:
            raw_out, n_facts = parse_and_save(str(f), company)
            print(f"  extracted {n_facts} facts -> {raw_out.name}")
        except Exception as e:
            print(f"  FAILED to parse: {e}")
            continue

        try:
            canonical_out, n_periods = map_and_save(raw_out)
            print(f"  mapped {n_periods} period record(s) -> {canonical_out.name}")
            results.append(canonical_out)
        except Exception as e:
            print(f"  FAILED to map: {e}")
        print()

    print(f"[run_extraction] Done. {len(results)}/{len(xbrl_files)} file(s) fully processed.")
    print(f"Next: from data_analysis, run:")
    print(f"  python -m src.analysis.combine_and_analyze {company} consolidated")
    print(f"  python -m src.analysis.combine_and_analyze {company} standalone")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.extract.run_extraction <company_symbol> [raw_dir]")
        sys.exit(1)
    company = sys.argv[1]
    raw_dir = sys.argv[2] if len(sys.argv) > 2 else None
    run_for_company(company, raw_dir)
