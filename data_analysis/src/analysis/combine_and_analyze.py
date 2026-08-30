import json
import sys
from pathlib import Path

from src.analysis.ratios import analyze, format_ratio_value
from src.config import EXTRACTED_DIR, ANALYSIS_OUTPUT_DIR


def find_canonical_files(company: str, filing_type: str, extracted_dir: Path = EXTRACTED_DIR) -> list[Path]:
    pattern = f"{company}_{filing_type}_*_canonical.json"
    files = sorted(Path(extracted_dir).glob(pattern))
    return files


def combine(company: str, filing_type: str, extracted_dir: Path = EXTRACTED_DIR) -> dict:
    files = find_canonical_files(company, filing_type, extracted_dir)
    if not files:
        print(f"[combine_and_analyze] No files matched '{company}_{filing_type}_*_canonical.json' "
              f"under {extracted_dir}/ — check the company/filing_type spelling, or run "
              f"xbrl_lite_parser.py + schema.py on more quarters first.")
        return {"periods": [], "trends": []}

    all_records = []
    seen_context_period = set()
    for f in files:
        records = json.loads(f.read_text())
        for r in records:
            # De-dupe: if the same context/period somehow appears in two
            # files (e.g. you re-ran extraction on the same quarter
            # twice), keep only the first occurrence rather than
            # double-counting it in the combined trend.
            key = (r.get("context_id"), r.get("period_end"), r.get("instant"))
            if key in seen_context_period:
                continue
            seen_context_period.add(key)
            r["_source_file"] = f.name
            all_records.append(r)

    print(f"[combine_and_analyze] Combined {len(files)} file(s), {len(all_records)} unique period record(s):")
    for f in files:
        print(f"  - {f.name}")

    return analyze(all_records)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m src.analysis.combine_and_analyze <company_symbol> <consolidated|standalone>")
        print("Example: python -m src.analysis.combine_and_analyze TCS consolidated")
        sys.exit(1)

    company = sys.argv[1]
    filing_type = sys.argv[2]

    result = combine(company, filing_type)

    out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_combined_ratios.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"\nSaved combined analysis to {out_path}\n")

    for p in result["periods"]:
        label = f"{p.get('period_start')} to {p.get('period_end')}" if p.get("period_start") else (p.get("period_end") or p.get("instant"))
        print(f"--- period={label} (context={p['context_id']}, source={p.get('_source_file')}) ---")
        for k, v in p["ratios"].items():
            print(f"  {k:50s} = {format_ratio_value(k, v)}")
        print()

    if result["trends"]:
        print("--- Period-over-period trends across all quarters ---")
        for t in result["trends"]:
            print(f"{t['from_period']} -> {t['to_period']}")
            for k, v in t.items():
                if k in ("from_period", "to_period"):
                    continue
                print(f"  {k:30s} = {format_ratio_value(k, v)}")
    else:
        print("(Not enough periods with dates to compute trends yet.)")
