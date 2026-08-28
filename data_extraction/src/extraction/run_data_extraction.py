
import json,time

from src.config import COMPANIES, REQUEST_DELAY_SECONDS
from src.extraction import nse_source


def extract_attachment_url(record: dict, source: str) -> str | None:
    """Best-effort extraction of a document URL from an NSE/BSE record.
    Different endpoints use different key names for the attachment link;
    """
    if source == "NSE":
        for key in ("attchmntFile", "attachment", "fileUrl", "xbrl", "pdfLink"):
            if record.get(key):
                url = record[key]
                return url if url.startswith("http") else f"https://nsearchives.nseindia.com/{url.lstrip('/')}"
    return None


def run_for_company(company:dict):
    nse_symbol = company["nse_symbol"]
    bse_scrip = company["bse_scrip"]
    print(f"\n=== {company['name']} ({nse_symbol} / {bse_scrip}) ===")

    # Getting prices
    print(f"Fetching {company['name']} price history...")
    prices = nse_source.fetch_price_history(nse_symbol)
    print(f"  -> {len(prices)} rows saved to data/prices/{nse_symbol}_prices.csv")

        # 2. NSE financial filings
    print("Fetching NSE integrated filings (financials)...")
    nse_filings = nse_source.fetch_corporate_filings(nse_symbol)
    # Uncomment on first live run to inspect the real response shape:
    print(json.dumps(nse_filings[:1], indent=2))
    # downloaded = 0
    # for rec in nse_filings:
    #     url = extract_attachment_url(rec, source="NSE")
    #     if not url:
    #         continue
    #     title = rec.get("companyName", "") + "_" + rec.get("subject", "filing")
    #     period = rec.get("periodEnded") or rec.get("period", "unknown_period")
    #     result = pdf_downloader.download_filing(
    #         nse_symbol, url, title=title, period=period, source="NSE", extra_meta=rec
    #     )
    #     if result:
    #         downloaded += 1
    # print(f"  -> {downloaded} new NSE filing document(s) downloaded")

def main():
    for company in COMPANIES:
        try:
            run_for_company(company)
        except Exception as e:
            # One company's failure shouldn't kill the whole run.
            print(f"[run_pipeline] FAILED for {company['nse_symbol']}: {e}")
        time.sleep(REQUEST_DELAY_SECONDS)


if __name__ == "__main__":
    main()
