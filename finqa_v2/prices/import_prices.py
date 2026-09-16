"""Import EOD share prices into finqa_v2.db `share_prices`.

Source: `data_extraction/data/prices/<SYMBOL>_prices.csv` (NSE bhavcopy-style export;
columns DATE, CLOSE, VWAP, VOLUME, SYMBOL, ...). Idempotent via (company_id, price_date)
upsert + a per-file `price_feed` source keyed on the file's sha256.

    python -m finqa_v2.prices.import_prices [--dry-run] [--company TCS]
        [--prices-dir PATH] [--v2-db PATH]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from finqa_v2.models import SharePrice, Source
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PRICES_DIR = _REPO_ROOT / "data_extraction" / "data" / "prices"


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if not s or s in ("-", "NA", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(s: str) -> date | None:
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _symbol_of(path: Path) -> str:
    return path.name.split("_prices")[0].split("_")[0]


def import_prices_file(path: Path, repos, *, dry_run: bool = False) -> dict:
    symbol = _symbol_of(path)
    company = repos.companies.resolve(symbol)
    if company is None:
        return {"file": path.name, "skipped": f"unknown company {symbol!r}"}

    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    prices: list[SharePrice] = []
    seen: set[date] = set()
    for row in rows:
        d = _parse_date(row.get("DATE") or row.get("Date") or "")
        if d is None or d in seen:
            continue
        seen.add(d)
        close = _num(row.get("CLOSE") or row.get("Close"))
        prices.append(SharePrice(
            company_id=company.company_id, price_date=d, close=close,
            vwap=_num(row.get("VWAP")), volume=_num(row.get("VOLUME") or row.get("Volume")),
        ))
    if not prices:
        return {"file": path.name, "skipped": "no usable rows"}

    if dry_run:
        return {"file": path.name, "company": symbol, "rows": len(prices),
                "date_min": min(p.price_date for p in prices).isoformat(),
                "date_max": max(p.price_date for p in prices).isoformat(), "written": 0}

    src = repos.sources.add(Source(
        kind="price_feed", company_id=company.company_id,
        document_title=f"{symbol} EOD prices", uri=str(path), content_hash=digest,
        exchange=company.exchange, retrieved_at=datetime.now(),
    ))
    prices = [replace(p, source_id=src.source_id) for p in prices]
    written = repos.prices.add_prices(prices)
    return {"file": path.name, "company": symbol, "rows": len(prices), "written": written,
            "date_min": min(p.price_date for p in prices).isoformat(),
            "date_max": max(p.price_date for p in prices).isoformat()}


def import_prices_dir(repos, prices_dir: Path = _PRICES_DIR, *, company: str | None = None,
                      dry_run: bool = False) -> dict:
    files = sorted(prices_dir.glob("*_prices.csv"))
    if company:
        files = [f for f in files if _symbol_of(f) == company]
    summary = {"files": len(files), "processed": 0, "skipped": 0, "prices": 0,
               "companies": set(), "skipped_files": []}
    for f in files:
        res = import_prices_file(f, repos, dry_run=dry_run)
        if res.get("skipped"):
            summary["skipped"] += 1
            summary["skipped_files"].append(f"{res['file']}: {res['skipped']}")
        else:
            summary["processed"] += 1
            summary["prices"] += res.get("written", 0)
            summary["companies"].add(res["company"])
    if not dry_run:
        repos.commit()
    summary["companies"] = sorted(summary["companies"])
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--company")
    ap.add_argument("--prices-dir", type=Path, default=_PRICES_DIR)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    args = ap.parse_args(argv)

    with SqliteRepositories(args.v2_db) as repos:
        summary = import_prices_dir(repos, args.prices_dir, company=args.company,
                                    dry_run=args.dry_run)
    print(f"prices: {summary['processed']}/{summary['files']} files, "
          f"{summary['prices']} rows written, {len(summary['companies'])} companies"
          f"{' (dry run)' if args.dry_run else ''}")
    for s in summary["skipped_files"][:20]:
        print("  skip:", s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
