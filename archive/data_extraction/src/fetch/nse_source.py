"""
NSE data acquistion:
1. Price/volume history (jugaad_data.nse.stock_df) -> needed later for
   valuation ratios (P/E, P/B) in the analysis phase, not fundamentals
   themselves.
2. Corporate filings / integrated filings (jugaad_data.nse.NSELive).

"""
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.config import REQUEST_DELAY_SECONDS, PRICE_DIR

os.environ.setdefault("J_CACHE_DIR", str(PRICE_DIR.parent / ".nse_cache"))

from jugaad_data.nse import NSELive, stock_df
from jugaad_data.util import break_dates, kw_to_fname


def _bust_current_month_price_cache(symbol: str, from_date: date, to_date: date, series: str = "EQ") -> None:
    try:
        chunks = break_dates(from_date, to_date)
        if not chunks:
            return
        last_from, last_to = chunks[-1]
        cache_dir = Path(os.environ["J_CACHE_DIR"]) / "nsehistory-stock"
        stale_path = cache_dir / kw_to_fname(symbol=symbol, from_date=last_from, to_date=last_to, series=series)
        stale_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"[nse_source] Couldn't clear the current-month price cache entry for {symbol} "
              f"(continuing anyway, but today's close may come back stale again): {e}")


# fetch the Open, High, Low, Close values for given days.
def fetch_price_history(nse_symbol: str, days_back: int = 365, output_symbol: str | None = None) -> pd.DataFrame:
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    _bust_current_month_price_cache(nse_symbol, from_date, to_date, series="EQ")
    df = stock_df(symbol=nse_symbol, from_date=from_date, to_date=to_date, series="EQ")
    out_path = PRICE_DIR / f"{output_symbol or nse_symbol}_prices.csv"
    df.to_csv(out_path, index=False)
    time.sleep(REQUEST_DELAY_SECONDS)
    return df


def fetch_corporate_filings(nse_symbol: str, days_back: int = 1095) -> list[dict]:
    """
    Pull recent 'Integrated Filing - Financials' entries for one company.
    Returns a list of dicts as given by NSE's API — each typically
    includes an attachment URL to the actual filed document.
    """
    nse = NSELive()
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    try:
        result = nse.corporate_integrated_filing(
            symbol=nse_symbol,
            filing_type="Integrated Filing- Financials",
            from_date=from_date,
            to_date=to_date,
        )
    except Exception as e:
        print(f"[nse_source] integrated_filing failed for {nse_symbol}: {e}")
        result = {}
    time.sleep(REQUEST_DELAY_SECONDS)

    # NSE wraps results under a 'data' key in most integrated-filing responses;
    # fall back gracefully if the shape differs.
    records = result.get("data", result) if isinstance(result, dict) else result
    return records or []


def fetch_corporate_announcements(nse_symbol: str, days_back: int = 1095) -> list[dict]:
    """
    Broader net than fetch_corporate_filings: general corporate
    announcements (includes results, but also other disclosures).
    Useful as a secondary source / cross-check, and for catching things
    like auditor resignations for the red-flag layer later. Can be useful for model tuning.
    """
    nse = NSELive()
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    try:
        result = nse.corporate_announcements(
            segment="equities", from_date=from_date, to_date=to_date, symbol=nse_symbol
        )
    except Exception as e:
        print(f"[nse_source] corporate_announcements failed for {nse_symbol}: {e}")
        result = []
    time.sleep(REQUEST_DELAY_SECONDS)
    return result or []