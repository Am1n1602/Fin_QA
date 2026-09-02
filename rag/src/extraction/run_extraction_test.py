"""
[TEST ONLY]
Usage:
    python -m src.extraction.run_extraction_test --meta-dir ../data_extraction/data/meta
    python -m src.extraction.run_extraction_test --meta-dir ../data_extraction/data/meta --symbol TCS --source BSE --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pdf_extractor import extract_pdf_text

CANDIDATE_KEYS = {
    "file_path": ["file_path", "local_path", "path", "filepath", "saved_path"],
    "source": ["source", "exchange", "src"],
    "sha256": ["sha256", "sha256_hash", "hash", "file_hash"],
    "title": ["title", "description", "doc_title", "subject", "attachment_name", "name"],
    "symbol": ["symbol", "company_symbol", "company"],
}


def resolve_field(record: dict, field_name: str) -> tuple[str | None, str | None]:
    """Returns (value, key_used). value is None if no candidate key matched."""
    for key in CANDIDATE_KEYS[field_name]:
        if key in record and record[key]:
            return record[key], key
    return None, None


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] {path.name} line {line_no}: could not parse JSON ({e}), skipping")
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--meta-dir", default="../data_extraction/data/meta",
                     help="Directory containing {symbol}_filings.jsonl inventory files "
                          "(default assumes rag/ and data_extraction/ are sibling dirs — "
                          "confirm this path is correct for your layout)")
    ap.add_argument("--symbol", default=None, help="Only process this symbol (e.g. TCS)")
    ap.add_argument("--source", default=None, help="Only process this source (e.g. BSE, NSE)")
    ap.add_argument("--limit", type=int, default=5, help="Max number of PDFs to extract")
    args = ap.parse_args()

    meta_dir = Path(args.meta_dir)
    if not meta_dir.exists():
        print(f"[ERROR] meta-dir not found: {meta_dir.resolve()}")
        print("        Pass the correct path with --meta-dir, e.g.:")
        print("        python -m src.extraction.run_extraction_test --meta-dir /full/path/to/data/meta")
        sys.exit(1)

    jsonl_files = sorted(meta_dir.glob("*_filings.jsonl"))
    if args.symbol:
        jsonl_files = [f for f in jsonl_files if f.name.upper().startswith(args.symbol.upper())]

    if not jsonl_files:
        print(f"[ERROR] No *_filings.jsonl files found in {meta_dir.resolve()}"
              + (f" matching symbol '{args.symbol}'" if args.symbol else ""))
        sys.exit(1)

    print(f"Found {len(jsonl_files)} inventory file(s): {[f.name for f in jsonl_files]}\n")

    all_records: list[tuple[str, dict]] = []  # (source_jsonl_filename, record)
    for jf in jsonl_files:
        recs = load_jsonl(jf)
        print(f"{jf.name}: {len(recs)} record(s)")
        all_records.extend((jf.name, r) for r in recs)

    if not all_records:
        print("[ERROR] No records loaded from any inventory file.")
        sys.exit(1)

    # Schema discovery: show the real keys of the first record
    first_file, first_record = all_records[0]
    print(f"\n--- Schema of first record (from {first_file}) ---")
    print(json.dumps(first_record, indent=2)[:1000])
    print("--- end schema sample ---\n")

    # Resolve required fields for the first record as a sanity check
    file_path_val, file_path_key = resolve_field(first_record, "file_path")
    if file_path_key is None:
        print("[ERROR] Could not find a file-path field in the record above.")
        print(f"        Tried candidate keys: {CANDIDATE_KEYS['file_path']}")
        print(f"        Actual keys present: {list(first_record.keys())}")
        print("        Paste one real jsonl line back and I'll hardcode the correct key.")
        sys.exit(1)
    print(f"Resolved file_path via key '{file_path_key}' -> {file_path_val}")

    source_val, source_key = resolve_field(first_record, "source")
    print(f"Resolved source via key: {source_key!r} (value: {source_val!r})"
          if source_key else "[WARN] Could not resolve a 'source' field (NSE/BSE) — --source filtering will not work")

    # Filter by source if requested and resolvable
    filtered = all_records
    if args.source:
        if source_key is None:
            print(f"[ERROR] --source '{args.source}' given but no source field could be resolved. Aborting rather than guessing.")
            sys.exit(1)
        filtered = [(fn, r) for fn, r in all_records if str(r.get(source_key, "")).upper() == args.source.upper()]
        print(f"\nFiltered to source='{args.source}': {len(filtered)} record(s)")

    filtered = filtered[: args.limit]
    print(f"\nExtracting {len(filtered)} PDF(s) (limit={args.limit})...\n")

    results = []
    for fn, record in filtered:
        path_val, _ = resolve_field(record, "file_path")
        sha_val, _ = resolve_field(record, "sha256")
        title_val, _ = resolve_field(record, "title")

        pdf_path = Path(path_val)
        if not pdf_path.is_absolute():
            # jsonl paths may be relative to the data_extraction project root
            # rather than to meta_dir or cwd — try a couple of reasonable bases.
            candidates = [pdf_path, meta_dir.parent.parent / pdf_path, meta_dir.parent / pdf_path]
            for c in candidates:
                if c.exists():
                    pdf_path = c
                    break

        print(f"=== {title_val or '(no title field)'} ===")
        print(f"    path: {pdf_path}")
        result = extract_pdf_text(pdf_path, known_sha256=sha_val)
        results.append((title_val, result))

        if not result.ok:
            print(f"    [FAIL] {result.error}")
        else:
            print(f"    pages: {result.page_count}, total_chars: {result.total_chars}, "
                  f"avg_chars/page: {result.total_chars / max(result.page_count, 1):.0f}")
            if result.low_text_page_numbers:
                print(f"    [FLAG] low-text pages (possible image/table/signature-only): {result.low_text_page_numbers}")
            preview = (result.pages[0].text[:200] if result.pages else "").replace("\n", " ")
            print(f"    page 1 preview: {preview}...")
        print()

    ok_count = sum(1 for _, r in results if r.ok)
    print(f"--- Summary: {ok_count}/{len(results)} extracted successfully ---")
    if ok_count < len(results):
        print("Some extractions failed — see [FAIL] lines above before proceeding to Phase 2 (chunking).")


if __name__ == "__main__":
    main()