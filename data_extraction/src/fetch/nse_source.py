"""
NSE data acquistion:
1. Price/volume history (jugaad_data.nse.stock_df) -> needed later for
   valuation ratios (P/E, P/B) in the analysis phase, not fundamentals
   themselves.
2. Corporate filings / integrated filings (jugaad_data.nse.NSELive).

"""
import time
from datetime import date, timedelta
import pandas as pd
from jugaad_data.nse import NSELive, stock_df

from src.config import REQUEST_DELAY_SECONDS, PRICE_DIR


# fetch the Open, High, Low, Close values for given days.
def fetch_price_history(nse_symbol: str, days_back: int = 180) -> pd.DataFrame:
    """Pull daily OHLCV history for one company and cache it to CSV."""
    to_date = date.today()
    from_date = to_date - timedelta(days=days_back)
    df = stock_df(symbol=nse_symbol, from_date=from_date, to_date=to_date, series="EQ")
    out_path = PRICE_DIR / f"{nse_symbol}_prices.csv"
    df.to_csv(out_path, index=False)
    time.sleep(REQUEST_DELAY_SECONDS)
    return df

# Inspect one response with print() the first time you run this to see
# the exact keys NSE returns (field names have shifted over API versions).

def fetch_corporate_filings(nse_symbol: str, days_back: int = 365) -> list[dict]:
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


def fetch_corporate_announcements(nse_symbol: str, days_back: int = 365) -> list[dict]:
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


