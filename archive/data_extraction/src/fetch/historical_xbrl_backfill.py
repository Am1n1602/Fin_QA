"""
One-off historical XBRL backfill: pulls FY2018-19 -> FY2023-24 'Financial Results'
(annual + quarterly, pre-Integrated-Filing) for a given set of companies from NSE's
older filing-type API, downloading only records with a real XBRL attachment (the
placeholder ".../xbrl/-" means no machine-readable file for that period).

See nse_source.fetch_historical_financial_results for the API details/gotchas.

    python -m src.fetch.historical_xbrl_backfill TCS RELIANCE HDFCBANK INFY ITC TATASTEEL SUNPHARMA
"""
import sys
from datetime import date

from src.fetch import nse_source, pdf_downloader

_FROM = date(2018, 4, 1)
_TO = date(2025, 3, 31)   # generous upper bound; the existing corpus's XBRL starts ~31-Mar-2025


def backfill_company(nse_symbol: str) -> int:
    downloaded = 0
    for period in ("Annual", "Quarterly"):
        records = nse_source.fetch_historical_financial_results(nse_symbol, _FROM, _TO, period=period)
        real = [r for r in records if r.get("xbrl") and not r["xbrl"].endswith("/-")]
        print(f"  {nse_symbol} {period}: {len(records)} filings found, {len(real)} with real XBRL")
        for rec in real:
            # xbrl_lite_parser detects basis via `"consolidated" in stem.lower()` --
            # which also matches inside "Non-Consolidated", so both bases would
            # collide as "consolidated" and silently overwrite each other unless
            # translated to match the existing "Standalone" naming the pipeline
            # already uses for Integrated Filing files.
            basis = "Standalone" if rec.get("consolidated") == "Non-Consolidated" else "Consolidated"
            title = f"Financial_Results_Original_{basis}"
            filing_period = rec.get("toDate") or rec.get("financialYear") or "unknown_period"
            result = pdf_downloader.download_filing(
                nse_symbol, rec["xbrl"], title=title, period=filing_period,
                source="NSE", extra_meta=rec,
            )
            if result:
                downloaded += 1
    return downloaded


def main():
    symbols = sys.argv[1:]
    if not symbols:
        print("Usage: python -m src.fetch.historical_xbrl_backfill TICKER [TICKER ...]")
        sys.exit(1)
    total = 0
    for sym in symbols:
        print(f"\n=== {sym} ===")
        try:
            total += backfill_company(sym)
        except Exception as e:
            print(f"[historical_xbrl_backfill] FAILED for {sym}: {e}")
    print(f"\nDone. {total} new historical XBRL file(s) downloaded.")


if __name__ == "__main__":
    main()
