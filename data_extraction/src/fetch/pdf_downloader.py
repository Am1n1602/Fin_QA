"""
Downloads filing PDFs (or XBRL files) to the local raw-data folder, and
records metadata for each one. Idempotent: re-running the pipeline will
skip URLs already recorded in the company's metadata index.
"""
import time
import requests

from src.config import USER_AGENT, REQUEST_DELAY_SECONDS
from src.extraction.data_storage import (
    company_raw_dir,
    already_downloaded,
    append_meta_record,
    safe_filename,
    file_hash,
)

def download_filing(
    nse_symbol: str,
    source_url: str,
    title: str,
    period: str,
    source: str,  # "NSE" or "BSE"
    extra_meta: dict | None = None,
    fallback_urls: list[str] | None = None,
) -> dict | None:
    """
    Download one filing document. Returns the metadata record written,
    or None if it was skipped (already downloaded) or failed.
    `fallback_urls` are tried in order if `source_url` fails (e.g. BSE's
    AttachHis path for older filings not found under AttachLive).
    """
    if already_downloaded(nse_symbol, source_url):
        return None

    resp = None
    for url in [source_url] + (fallback_urls or []):
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            resp.raise_for_status()
            source_url = url  # record whichever URL actually worked
            break
        except requests.RequestException as e:
            print(f"[pdf_downloader] failed to fetch {url}: {e}")
            resp = None

    if resp is None:
        return None

    ext = "pdf" if "pdf" in resp.headers.get("Content-Type", "").lower() else "bin"
    if source_url.lower().endswith((".xml", ".xbrl")):
        ext = "xbrl"

    fname = f"{safe_filename(period)}_{safe_filename(title)}.{ext}"
    out_dir = company_raw_dir(nse_symbol)
    out_path = out_dir / fname
    out_path.write_bytes(resp.content)

    record = {
        "company": nse_symbol,
        "source": source,
        "source_url": source_url,
        "title": title,
        "period": period,
        "local_path": str(out_path),
        "sha256": file_hash(out_path),
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if extra_meta:
        record.update(extra_meta)

    append_meta_record(nse_symbol, record)
    time.sleep(REQUEST_DELAY_SECONDS)
    return record
