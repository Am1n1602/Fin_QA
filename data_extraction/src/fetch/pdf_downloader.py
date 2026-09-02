"""
Downloads filing PDFs (or XBRL files) to the local raw-data folder, and
records metadata for each one. Idempotent: re-running the pipeline will
skip URLs already recorded in the company's metadata index.
"""
import time
import requests

from src.config import USER_AGENT, REQUEST_DELAY_SECONDS
from src.fetch.data_storage import (
    company_raw_dir,
    already_downloaded,
    find_existing_record_by_hash,
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
            candidate = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            candidate.raise_for_status()
        except requests.RequestException as e:
            print(f"[pdf_downloader] failed to fetch {url}: {e}")
            continue

        # A 200 status doesn't guarantee real content -- BSE/NSE sometimes serve
        # an HTML error/rate-limit/session page with status 200. Validate actual
        # bytes match what the URL/headers claim before trusting this response.
        is_xbrl_url = url.lower().endswith((".xml", ".xbrl"))
        looks_like_pdf = "pdf" in candidate.headers.get("Content-Type", "").lower() or url.lower().endswith(".pdf")

        if is_xbrl_url and not candidate.content.strip().startswith(b"<"):
            print(f"[pdf_downloader] {url}: expected XML/XBRL, got non-XML content "
                f"(first bytes: {candidate.content[:30]!r}) -- skipping, trying next URL if any")
            continue
        if looks_like_pdf and not candidate.content.startswith(b"%PDF-"):
            print(f"[pdf_downloader] {url}: expected a PDF, got non-PDF content "
                f"(first bytes: {candidate.content[:30]!r}) -- likely an HTML "
                f"error/rate-limit page served with status 200; skipping, trying next URL if any")
            continue

        resp = candidate
        source_url = url
        break
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
    existing = find_existing_record_by_hash(nse_symbol, record["sha256"])
    if existing is not None:
        print(f"[pdf_downloader] content already recorded as '{existing.get('title')}' "
              f"(sha256={record['sha256'][:16]}...) -- same file, different URL/title. "
              f"Recording as a duplicate reference, not re-storing.")
        out_path.unlink(missing_ok=True)  # remove the redundant just-written copy
        record["local_path"] = existing.get("local_path")  # point at the kept original
        record["duplicate_content_of"] = existing.get("title")


    append_meta_record(nse_symbol, record)
    time.sleep(REQUEST_DELAY_SECONDS)
    return record
