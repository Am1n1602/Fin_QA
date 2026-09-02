"""
[TEST ONLY]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.extraction.pdf_extractor import extract_pdf_text
from src.chunking.chunker import chunk_extraction_result


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
                     help="Directory containing {symbol}_filings.jsonl inventory files")
    ap.add_argument("--symbol", default=None, help="Only process this symbol (e.g. TCS)")
    ap.add_argument("--source", default=None, help="Only process this source (e.g. BSE, NSE)")
    ap.add_argument("--limit", type=int, default=8, help="Max number of PDFs to process")
    ap.add_argument("--chunk-size", type=int, default=1000)
    ap.add_argument("--overlap", type=int, default=150)
    ap.add_argument("--preview-chunks", type=int, default=2,
                     help="How many example chunks to print per document")
    args = ap.parse_args()

    meta_dir = Path(args.meta_dir)
    if not meta_dir.exists():
        print(f"[ERROR] meta-dir not found: {meta_dir.resolve()}")
        return

    jsonl_files = sorted(meta_dir.glob("*_filings.jsonl"))
    if args.symbol:
        jsonl_files = [f for f in jsonl_files if f.name.upper().startswith(args.symbol.upper())]
    if not jsonl_files:
        print(f"[ERROR] No *_filings.jsonl files found in {meta_dir.resolve()}")
        return

    all_records: list[dict] = []
    for jf in jsonl_files:
        recs = load_jsonl(jf)
        all_records.extend(recs)

    if args.source:
        all_records = [r for r in all_records if str(r.get("source", "")).upper() == args.source.upper()]

    pdf_records = [r for r in all_records if str(r.get("local_path", "")).lower().endswith((".pdf", ".bin"))]

    sha_groups: dict[str, list[dict]] = {}
    for r in pdf_records:
        sha = r.get("sha256")
        if sha:
            sha_groups.setdefault(sha, []).append(r)
    dupe_groups = {sha: recs for sha, recs in sha_groups.items() if len(recs) > 1}
    if dupe_groups:
        print(f"[WARNING] {len(dupe_groups)} sha256 value(s) have duplicate records "
              f"({sum(len(v) for v in dupe_groups.values())} total records involved). "
              f"This means identical file content is recorded more than once in the "
              f"jsonl inventory -- likely an upstream idempotency issue in the "
              f"downloader, not something this script causes. De-duplicating for "
              f"this run (keeping the first record per sha256); the duplicates "
              f"themselves still exist in your jsonl file.")
        for sha, recs in list(dupe_groups.items())[:5]:
            print(f"    sha256={sha[:16]}...: {len(recs)} records, titles: "
                  f"{[r.get('title') for r in recs]}")
        if len(dupe_groups) > 5:
            print(f"    ...and {len(dupe_groups) - 5} more duplicate group(s)")
        print()
        seen_sha = set()
        deduped = []
        for r in pdf_records:
            sha = r.get("sha256")
            if sha and sha in seen_sha:
                continue
            if sha:
                seen_sha.add(sha)
            deduped.append(r)
        pdf_records = deduped

    targets = pdf_records[: args.limit]
    print(f"Processing {len(targets)} document(s) "
          f"(of {len(pdf_records)} PDF/bin records matching filters, {len(all_records)} total records)\n")

    doc_summaries = []
    section_counter = Counter()
    all_chunk_lengths: list[int] = []
    total_skipped_pages = 0
    extraction_failures = 0

    for rec in targets:
        title = rec.get("title", "(no title)")
        local_path = rec.get("local_path")
        sha256 = rec.get("sha256")

        print(f"=== {title} ({rec.get('period', '?')}) ===")
        print(f"    path: {local_path}")

        result = extract_pdf_text(local_path, known_sha256=sha256)
        if not result.ok:
            print(f"    [EXTRACTION FAILED] {result.error}\n")
            extraction_failures += 1
            continue

        cr = chunk_extraction_result(result, chunk_size=args.chunk_size, overlap=args.overlap)
        lengths = [c.char_count for c in cr.chunks]
        all_chunk_lengths.extend(lengths)
        total_skipped_pages += len(cr.skipped_pages)
        for c in cr.chunks:
            section_counter[c.section or "(none)"] += 1

        print(f"    pages: {result.page_count}, chunks: {len(cr.chunks)}, "
              f"skipped_pages: {len(cr.skipped_pages)}")
        if cr.skipped_pages:
            skipped_nums = [sp["page_number"] for sp in cr.skipped_pages]
            print(f"    skipped page numbers: {skipped_nums}")
        if lengths:
            print(f"    chunk length: min={min(lengths)} max={max(lengths)} "
                  f"avg={sum(lengths)/len(lengths):.0f}")
        sections_seen = [c.section for c in cr.chunks if c.section]
        print(f"    sections detected: {sorted(set(sections_seen)) or '(none)'}")
        if cr.section_transitions:
            print(f"    section transitions (why each label was assigned):")
            for t in cr.section_transitions:
                print(f"      p{t['page_number']}: -> {t['section']}  "
                      f"(matched: ...{t['matched_snippet']}...)")

        for c in cr.chunks[: args.preview_chunks]:
            preview = c.text[:150].replace("\n", " ")
            print(f"    [chunk {c.chunk_index}, p{c.page_start}-{c.page_end}, {c.section}] {preview}...")

        doc_summaries.append({
            "title": title, "chunks": len(cr.chunks), "skipped_pages": len(cr.skipped_pages),
        })
        print()

    print("=" * 70)
    print(f"SUMMARY: {len(doc_summaries)} document(s) chunked successfully, "
          f"{extraction_failures} extraction failure(s)")
    if all_chunk_lengths:
        print(f"Total chunks: {len(all_chunk_lengths)}  "
              f"avg length: {sum(all_chunk_lengths)/len(all_chunk_lengths):.0f} chars  "
              f"min: {min(all_chunk_lengths)}  max: {max(all_chunk_lengths)}")
    print(f"Total skipped pages across all documents: {total_skipped_pages}")
    print(f"Section label distribution: {dict(section_counter)}")
    if extraction_failures:
        print("\nSome extractions failed -- see [EXTRACTION FAILED] lines above.")


if __name__ == "__main__":
    main()