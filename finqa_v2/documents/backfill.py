"""Backfill finqa_v2.db documents + document_chunks from data_extraction/data/raw/*/*.pdf.

Idempotent (source sha256 + chunk replace). See docs/file-guide.md.

    python -m finqa_v2.documents.backfill [--dry-run] [--company TCS] [--limit N]
        [--raw-dir PATH] [--v2-db PATH] [--no-tables]

`--company` also accepts a comma-separated list (e.g. `--company TCS,RELIANCE,INFY`) to
run a subset pilot before scaling to the full universe -- the same command just widens
the list later.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from finqa_v2.documents.pipeline import ingest_pdf
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RAW_DIR = _REPO_ROOT / "data_extraction" / "data" / "raw"


def _pdfs(raw_dir: Path, company: str | list[str] | None) -> list[Path]:
    if company:
        tickers = [company] if isinstance(company, str) else list(company)
        files: list[Path] = []
        for tkr in tickers:
            files.extend(sorted((raw_dir / tkr).glob("*.pdf")))
        return files
    return sorted(raw_dir.glob("*/*.pdf"))


def run_backfill(repos, raw_dir: Path = _RAW_DIR, *, company: str | list[str] | None = None,
                 limit=None, detect_tables=True) -> dict:
    """`files` is naturally grouped by company (`_pdfs` sorts `<raw_dir>/<COMPANY>/*.pdf`
    paths, so same-company files are contiguous). Commits once per company boundary --
    not just once at the very end -- so an interrupted run (killed, crashed, machine
    restart) loses at most the company in flight, not every company already ingested."""
    files = _pdfs(raw_dir, company)
    if limit:
        files = files[:limit]
    s = {"files": len(files), "ingested": 0, "skipped": 0, "chunks": 0, "tables": 0,
         "companies": set(), "skips": []}
    last_company_dir = None
    for p in files:
        company_dir = p.parent.name
        if last_company_dir is not None and company_dir != last_company_dir:
            repos.commit()
        last_company_dir = company_dir
        res = ingest_pdf(p, repos, detect_tables=detect_tables)
        if res.get("skipped"):
            s["skipped"] += 1
            s["skips"].append(f"{res['file']}: {res['skipped']}")
        else:
            s["ingested"] += 1
            s["chunks"] += res["chunks"]
            s["tables"] += res.get("tables", 0)
            s["companies"].add(res["company"])
    repos.commit()
    s["companies"] = sorted(s["companies"])
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", type=Path, default=_RAW_DIR)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--company", default=None,
                    help="one ticker, or a comma-separated list (e.g. TCS,RELIANCE,INFY)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-tables", action="store_true", help="Skip PyMuPDF table detection (faster).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.raw_dir.exists():
        raise SystemExit(f"raw dir not found: {args.raw_dir}")

    company = [c.strip() for c in args.company.split(",") if c.strip()] if args.company else None

    if args.dry_run:
        files = _pdfs(args.raw_dir, company)
        if args.limit:
            files = files[: args.limit]
        print(f"[dry-run] pdfs      : {len(files)}")
        print(f"[dry-run] companies : {len({p.parent.name for p in files})}")
        print(f"[dry-run] target db : {args.v2_db}")
        return 0

    with SqliteRepositories(args.v2_db) as repos:
        s = run_backfill(repos, args.raw_dir, company=company, limit=args.limit,
                         detect_tables=not args.no_tables)
    print(
        f"[documents] {s['ingested']}/{s['files']} PDFs -> {s['chunks']} chunks "
        f"({s['tables']} table chunks) across {len(s['companies'])} companies "
        f"({s['skipped']} skipped)"
    )
    for line in s["skips"][:20]:
        print(f"  skip: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
