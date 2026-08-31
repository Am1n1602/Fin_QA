"""
BSE data acquisition, via the unofficial `bse` (BseIndiaApi) library.

BSE is often the more reliable of the two exchanges to scrape for
announcement history (NSE's site leans harder on session/cookie checks).
`resultsSnapshot` in particular can give you parsed quarterly-result
figures directly for some companies — check its output before assuming
you need to go the PDF-extraction route at all for a given company.
"""
import time
from datetime import datetime, timedelta

from bse import BSE
from bse.constants import CATEGORY

from src.config import REQUEST_DELAY_SECONDS, BASE_DIR

# The bse library's BSE class writes some downloads (e.g. bhavcopy zips) to
# this folder internally — it's a required constructor argument even though
# our pipeline does its own downloading via pdf_downloader. Point it at a
# scratch folder under data/ so nothing lands somewhere unexpected.
_BSE_SCRATCH_DIR = BASE_DIR / "data" / "_bse_scratch"
_BSE_SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def get_scrip_code(company_name: str) -> str | None:
    """Resolve a BSE scrip code from a company name — run this once per
    company and hardcode the result in config.py rather than re-resolving
    it on every pipeline run."""
    with BSE(download_folder=_BSE_SCRATCH_DIR) as b:
        result = b.getScripCode(company_name)
    time.sleep(REQUEST_DELAY_SECONDS)
    return result


def fetch_announcements(bse_scrip: str, days_back: int = 1095) -> list[dict]:
    """
    Pull corporate announcements for one scrip, filtered to results-related
    categories where possible. Returns BSE's raw 'Table' list — each entry
    normally includes an ATTACHMENTNAME field that is the PDF filename,
    served from BSE's static attachment host.
    """
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)
    with BSE(download_folder=_BSE_SCRATCH_DIR) as b:
        data = b.announcements(
            from_date=from_date,
            to_date=to_date,
            segment="equity",
            scripcode=bse_scrip,
            category=CATEGORY.RESULT,
        )
    time.sleep(REQUEST_DELAY_SECONDS)
    return data.get("Table", []) if isinstance(data, dict) else []


def fetch_results_snapshot(bse_scrip: str) -> dict:
    """
    Pull BSE's own parsed quarterly-results snapshot for a scrip.
    This is a genuinely useful shortcut: if the fields you need are
    present here, you can skip PDF extraction entirely for this company
    and go straight to your validation layer.
    """
    with BSE(download_folder=_BSE_SCRATCH_DIR) as b:
        data = b.resultsSnapshot(bse_scrip)
    time.sleep(REQUEST_DELAY_SECONDS)
    return data or {}


def build_attachment_url(attachment_name: str) -> str:
    """
    BSE serves recent announcement attachments from AttachLive, keyed by
    the ATTACHMENTNAME field returned in announcements(). Older/historical
    filings sometimes live under AttachHis instead — if a download 404s,
    retry with 'AttachHis' in place of 'AttachLive' before giving up on
    that record.
    """
    return f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{attachment_name}"


def build_attachment_url_historical(attachment_name: str) -> str:
    """Fallback for filings not found under AttachLive."""
    return f"https://www.bseindia.com/xml-data/corpfiling/AttachHis/{attachment_name}"
