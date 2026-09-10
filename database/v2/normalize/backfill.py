"""Backfill finqa_v2.db financial_facts + sources from data_extraction/*_canonical.json.

Idempotent (fact grain + source content-hash). See docs/file-guide.md.

    python -m database.v2.normalize.backfill [--dry-run] [--company TCS] [--limit N]
        [--extracted-dir PATH] [--v2-db PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from database.v2.normalize.pipeline import _parse_filename, normalize_canonical_file
from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EXTRACTED_DIR = _REPO_ROOT / "data_extraction" / "data" / "extracted"


def _canonical_files(extracted_dir: Path, company: str | None) -> list[Path]:
    out = []
    for p in sorted(extracted_dir.glob("*_canonical.json")):
        parsed = _parse_filename(p.name)
        if parsed is None:
            continue
        if company and parsed[0] != company:
            continue
        out.append(p)
    return out


def run_backfill(
    repos,
    extracted_dir: Path = _EXTRACTED_DIR,
    *,
    company: str | None = None,
    limit: int | None = None,
) -> dict:
    files = _canonical_files(extracted_dir, company)
    if limit:
        files = files[:limit]

    summary = {
        "files": len(files), "processed": 0, "skipped": 0, "facts": 0,
        "skipped_files": [], "companies": set(),
    }
    for path in files:
        res = normalize_canonical_file(path, repos)
        if res.get("skipped"):
            summary["skipped"] += 1
            summary["skipped_files"].append(f"{res['file']}: {res['skipped']}")
        else:
            summary["processed"] += 1
            summary["facts"] += res["facts"]
            summary["companies"].add(res["company"])
    repos.commit()
    summary["companies"] = sorted(summary["companies"])
    return summary


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
        files = _canonical_files(args.extracted_dir, args.company)
        if args.limit:
            files = files[: args.limit]
        companies = sorted({_parse_filename(p.name)[0] for p in files})
        print(f"[dry-run] extracted dir : {args.extracted_dir}")
        print(f"[dry-run] canonical files: {len(files)}")
        print(f"[dry-run] companies      : {len(companies)}")
        print(f"[dry-run] target db      : {args.v2_db}")
        return 0

    with SqliteRepositories(args.v2_db) as repos:
        s = run_backfill(repos, args.extracted_dir, company=args.company, limit=args.limit)

    print(
        f"[backfill] {s['processed']}/{s['files']} files -> {s['facts']} facts "
        f"across {len(s['companies'])} companies ({s['skipped']} skipped)"
    )
    for line in s["skipped_files"][:20]:
        print(f"  skip: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
