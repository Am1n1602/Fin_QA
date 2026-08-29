
import json,time

from src.config import COMPANIES, REQUEST_DELAY_SECONDS, META_DIR
from src.fetch import nse_source, pdf_downloader,bse_source


def extract_attachment_url(record: dict, source: str) -> str | None:
    """Best-effort extraction of a document URL from an NSE/BSE record.
    Different endpoints use different key names for the attachment link;
    try the common ones and fall back to None (meaning: nothing to
    download for this record, e.g. it's a text-only disclosure)."""
    if source == "NSE":
        for key in ("xbrl", "ixbrl", "pdf_attach"):
            url = record.get(key)
            if url and url.startswith("http") and not url.endswith("/null"):
                return url
    elif source == "BSE":
        attachment_name = record.get("ATTACHMENTNAME") or record.get("Attachname")
        if attachment_name:
            return bse_source.build_attachment_url(attachment_name)
    return None



def run_for_company(company: dict):
    nse_symbol = company["nse_symbol"]
    bse_scrip = company["bse_scrip"]
    print(f"\n=== {company['name']} ({nse_symbol} / {bse_scrip}) ===")

    # 1. Price history
    print("Fetching price history...")
    prices = nse_source.fetch_price_history(nse_symbol)
    print(f"  -> {len(prices)} rows saved to data/prices/{nse_symbol}_prices.csv")

    # 2. NSE financial filings
    print("Fetching NSE integrated filings (financials)...")
    nse_filings = nse_source.fetch_corporate_filings(nse_symbol)
    # Uncomment on first live run to inspect the real response shape:
    print(json.dumps(nse_filings[:1], indent=2))
    downloaded = 0
    for rec in nse_filings:
        url = extract_attachment_url(rec, source="NSE")
        if not url:
            continue
        title = f"{rec.get('type', 'filing')}_{rec.get('type_Sub', '')}_{rec.get('consolidated', '')}"
        period = rec.get("qe_Date", "unknown_period")
        result = pdf_downloader.download_filing(
            nse_symbol, url, title=title, period=period, source="NSE", extra_meta=rec
        )
        if result:
            downloaded += 1
    print(f"  -> {downloaded} new NSE filing document(s) downloaded")

    # 3. BSE announcements (broader net, incl. results + governance-relevant items)
    print("Fetching BSE announcements...")
    bse_announcements = bse_source.fetch_announcements(bse_scrip)
    print(json.dumps(bse_announcements[:1], indent=2))
    downloaded_bse = 0
    for rec in bse_announcements:
        url = extract_attachment_url(rec, source="BSE")
        if not url:
            continue
        title = rec.get("NEWSSUB") or rec.get("HEADLINE") or "announcement"
        period = rec.get("NEWS_DT") or rec.get("DissemDT") or "unknown_date"
        attachment_name = rec.get("ATTACHMENTNAME") or rec.get("Attachname")
        fallback = (
            [bse_source.build_attachment_url_historical(attachment_name)]
            if attachment_name
            else None
        )
        result = pdf_downloader.download_filing(
            nse_symbol,
            url,
            title=title,
            period=period,
            source="BSE",
            extra_meta=rec,
            fallback_urls=fallback,
        )
        if result:
            downloaded_bse += 1
    print(f"  -> {downloaded_bse} new BSE announcement document(s) downloaded")

    # 4. BSE results snapshot (pre-parsed numbers, worth checking before PDF extraction)
    print("Fetching BSE results snapshot...")
    snapshot = bse_source.fetch_results_snapshot(bse_scrip)
    snapshot_path = META_DIR / f"{nse_symbol}_bse_results_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2))
    print(f"  -> saved to {snapshot_path}")


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
