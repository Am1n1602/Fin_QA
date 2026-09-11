"""
Narrative-document acquisition from BSE (Fin_QA v2, Phase 15).

`bse_source.fetch_announcements` filters to `CATEGORY.RESULT`, which is why the
finqa_v2 corpus is quarterly-results PDFs only and the "why" / cross-validation
answers lack management-commentary support. This module pulls the narrative
documents -- earnings-call transcripts (the biggest lift: verbatim management Q&A
about why the numbers moved), investor presentations, annual reports, BRSR --
across a multi-year window into `data/raw/<SYMBOL>/`, where
`finqa_v2.documents.backfill` already knows how to ingest `annual_report` /
`transcript` / `investor_presentation` types, and `finqa_v2/documents/sections.py`
has the board_report / corporate_governance / brsr / earnings_call rules.

BSE's `announcements` endpoint caps the date range per call and needs an explicit
category, so we sweep 75-day windows across AGM / Company-Update / Others.

    python -m src.fetch.annual_reports --symbols TCS INFY --years 2
    python -m src.fetch.annual_reports --all --years 2 --kinds transcript investor_presentation brsr
    python -m src.fetch.annual_reports --all --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from bse import BSE
from bse.constants import CATEGORY

from src.config import BASE_DIR
from src.fetch.pdf_downloader import download_filing

_RAW = BASE_DIR / "data" / "raw"
_SCRATCH = BASE_DIR / "data" / "_bse_scratch"
_UNIVERSE = BASE_DIR / "data" / "universe" / "nifty50_constituents.json"
_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{name}"
_ATTACH_HIS = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{name}"
# narrative filings live under AGM (annual report / notice), Company-Update (transcripts,
# investor presentations) and Others (BRSR). Board-Meeting carries nothing narrative.
_CATEGORIES = (CATEGORY.AGM, CATEGORY.UPDATE, CATEGORY.OTHERS)
_WINDOW_DAYS = 88                        # BSE caps the announcements date range near 90 days
_MIN_FREE_GB = 1.2                       # stop downloading if the disk gets this low
_DELAY = 0.6                             # between BSE calls (the `bse` lib also self-throttles)

# subject -> our document_type. "audio" filings are recordings, not text -- skip them.
_SKIP = re.compile(r"\baudio\b|\bvideo\b|scrutinizer|voting results|newspaper", re.I)
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"earnings call transcript|analyst call transcript|investor call.*transcript|"
                r"transcript of (the )?(investor|analyst|earnings)|analyst day.*transcript", re.I),
     "transcript"),
    (re.compile(r"investor presentation|earnings presentation|analyst presentation", re.I),
     "investor_presentation"),
    (re.compile(r"annual report", re.I), "annual_report"),
    (re.compile(r"business responsibility.*sustainability|\bBRSR\b", re.I), "brsr"),
]


def _classify(subject: str) -> str | None:
    if _SKIP.search(subject):
        return None
    for pat, kind in _RULES:
        if pat.search(subject):
            return kind
    return None


def _windows(years: float):
    end = datetime.now()
    days = int(years * 365) + 20
    while days > 0:
        start = end - timedelta(days=min(_WINDOW_DAYS, days))
        yield start, end
        end = start - timedelta(days=1)
        days -= _WINDOW_DAYS


def _free_gb() -> float:
    return shutil.disk_usage(str(BASE_DIR)).free / 1e9


def fetch_for_symbol(bse: BSE, symbol: str, scrip: str, *, years: float,
                     kinds: set[str], dry_run: bool) -> dict:
    seen: dict[str, dict] = {}
    for (start, end) in _windows(years):
        for cat in _CATEGORIES:
            try:
                data = bse.announcements(from_date=start, to_date=end, scripcode=scrip, category=cat)
            except Exception:
                continue
            for r in (data.get("Table", []) if isinstance(data, dict) else data) or []:
                subject = (r.get("NEWSSUB") or r.get("HEADLINE") or "").strip()
                attach = r.get("ATTACHMENTNAME")
                kind = _classify(subject)
                if not attach or kind is None or kind not in kinds or attach in seen:
                    continue
                seen[attach] = {"subject": subject, "kind": kind,
                                "date": (r.get("NEWS_DT") or "")[:10]}
            time.sleep(_DELAY)

    items = sorted(seen.items(), key=lambda kv: kv[1]["date"], reverse=True)
    downloaded, skipped_disk = 0, 0
    if not dry_run:
        for name, meta in items:
            if _free_gb() < _MIN_FREE_GB:
                skipped_disk += 1
                continue
            try:
                rec = download_filing(
                    symbol, _ATTACH.format(name=name),
                    title=f"{meta['kind']} {meta['subject'][:90]}".strip(),
                    period=meta["date"], source="BSE",
                    extra_meta={"doc_type": meta["kind"], "subject": meta["subject"]},
                    fallback_urls=[_ATTACH_HIS.format(name=name)],
                )
                if rec is not None:
                    downloaded += 1
                time.sleep(_DELAY)
            except Exception as e:
                meta["error"] = str(e)
    by_kind: dict[str, int] = {}
    for _, m in items:
        by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    return {"symbol": symbol, "candidates": len(items), "by_kind": by_kind,
            "downloaded": downloaded, "skipped_disk": skipped_disk,
            "items": [m for _, m in items]}


def _universe() -> list[tuple[str, str]]:
    payload = json.loads(_UNIVERSE.read_text(encoding="utf-8"))
    out = []
    for e in payload.get("companies", []):
        sym, scrip = e.get("nse_symbol"), e.get("bse_scrip")
        if sym and scrip:
            out.append((sym, str(scrip)))
    return out


def main(argv=None) -> int:
    global _DELAY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbols", nargs="+", metavar="SYM")
    g.add_argument("--all", action="store_true", help="every NIFTY-50 constituent")
    ap.add_argument("--years", type=float, default=1.5)
    ap.add_argument("--kinds", nargs="+",
                    default=["transcript", "investor_presentation", "brsr", "annual_report"],
                    choices=["transcript", "investor_presentation", "brsr", "annual_report"])
    ap.add_argument("--delay", type=float, default=_DELAY)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    _DELAY = args.delay

    _SCRATCH.mkdir(parents=True, exist_ok=True)
    uni = dict(_universe())
    targets = list(uni.items()) if args.all else [(s, uni.get(s, "")) for s in args.symbols]
    kinds = set(args.kinds)

    tot = {"candidates": 0, "downloaded": 0, "skipped_disk": 0}
    with BSE(download_folder=_SCRATCH) as bse:
        for sym, scrip in targets:
            if not scrip:
                print(f"  {sym}: no bse_scrip -- skipped")
                continue
            try:
                res = fetch_for_symbol(bse, sym, scrip, years=args.years, kinds=kinds,
                                       dry_run=args.dry_run)
            except Exception as e:
                print(f"  {sym}: FAILED ({type(e).__name__}: {e})")
                continue
            for k in tot:
                tot[k] += res.get(k, 0)
            print(f"  {sym:12} {res['by_kind']}  downloaded={res['downloaded']}"
                  f"{'  disk-skipped=' + str(res['skipped_disk']) if res['skipped_disk'] else ''}"
                  f"{'  (dry run)' if args.dry_run else ''}")

    print(f"\ntotal: {tot['candidates']} candidates, {tot['downloaded']} downloaded, "
          f"{tot['skipped_disk']} disk-skipped   (free {_free_gb():.1f} GB)")
    print("next: python -m finqa_v2.documents.backfill && "
          "python -m finqa_v2.retrieval.build_indexes && python -m finqa_v2.dataset.audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
