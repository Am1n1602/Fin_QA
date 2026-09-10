"""Backfill finqa_v2.db segments + segment_facts from *_facts_raw.json.

Idempotent (segment (company,slug) + fact grain + source hash). See docs/file-guide.md.

    python -m finqa_v2.normalize.backfill_segments [--dry-run] [--company TCS] [--limit N]
        [--extracted-dir PATH] [--v2-db PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from finqa_v2.normalize.pipeline import _parse_filename
from finqa_v2.normalize.segments import extract_and_store
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXTRACTED_DIR = _REPO_ROOT / "data_extraction" / "data" / "extracted"


def _raw_files(extracted_dir: Path, company: str | None) -> list[Path]:
    out = []
    for p in sorted(extracted_dir.glob("*_facts_raw.json")):
        parsed = _parse_filename(p.name.replace("_facts_raw.json", "_canonical.json"))
        if parsed is None or (company and parsed[0] != company):
            continue
        out.append(p)
    return out


def run_backfill(repos, extracted_dir: Path = _EXTRACTED_DIR, *, company=None, limit=None) -> dict:
    files = _raw_files(extracted_dir, company)
    if limit:
        files = files[:limit]
    s = {"files": len(files), "with_segments": 0, "fact_upserts": 0, "skipped": 0, "companies": set()}
    for p in files:
        res = extract_and_store(p, repos)
        if res.get("skipped"):
            s["skipped"] += 1
        elif res["segments"]:
            s["with_segments"] += 1
            s["fact_upserts"] += res["facts"]
            s["companies"].add(res["company"])
    repos.commit()
    s["companies"] = sorted(s["companies"])
    s["distinct_segments"] = repos.connection.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    s["distinct_segment_facts"] = repos.connection.execute("SELECT COUNT(*) FROM segment_facts").fetchone()[0]
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extracted-dir", type=Path, default=_EXTRACTED_DIR)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--company", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.extracted_dir.exists():
        raise SystemExit(f"extracted dir not found: {args.extracted_dir}")

    if args.dry_run:
        files = _raw_files(args.extracted_dir, args.company)
        if args.limit:
            files = files[: args.limit]
        print(f"[dry-run] raw files : {len(files)}")
        print(f"[dry-run] target db : {args.v2_db}")
        return 0

    with SqliteRepositories(args.v2_db) as repos:
        s = run_backfill(repos, args.extracted_dir, company=args.company, limit=args.limit)
    print(
        f"[segments] {s['with_segments']}/{s['files']} files had segments -> "
        f"{s['distinct_segments']} segments, {s['distinct_segment_facts']} segment_facts "
        f"across {len(s['companies'])} companies ({s['fact_upserts']} upserts)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
