"""
Main Database of Companies, storage path.
"""

import json
from pathlib import Path


# FILL THIS 
_FALLBACK_COMPANIES = [
    {"name": "Tata Consultancy Services", "nse_symbol": "TCS", "bse_scrip": "532540"},
    {"name": "Infosys", "nse_symbol": "INFY", "bse_scrip": "500209"},
    {"name": "HCL Technologies", "nse_symbol": "HCLTECH", "bse_scrip": "532281"},
    {"name": "Wipro", "nse_symbol": "WIPRO", "bse_scrip": "507685"},
    {"name": "Tech Mahindra", "nse_symbol": "TECHM", "bse_scrip": "532755"},
    {"name": "LTIMindtree", "nse_symbol": "LTM", "bse_scrip": "540005"},
]


def _load_companies() -> list[dict]:
    cache_path = Path(__file__).resolve().parent.parent / "data" / "universe" / "nifty50_constituents.json"
    if not cache_path.exists():
        return _FALLBACK_COMPANIES

    try:
        payload = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return _FALLBACK_COMPANIES

    companies = [
        {"name": e["name"], "nse_symbol": e["nse_symbol"], "bse_scrip": e["bse_scrip"]}
        for e in payload.get("companies", [])
        if e.get("active", True) and e.get("bse_scrip")
    ]
    return companies or _FALLBACK_COMPANIES


COMPANIES = _load_companies()

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"          # raw downloaded PDFs
META_DIR = BASE_DIR / "data" / "meta"        # metadata json/csv index
PRICE_DIR = BASE_DIR / "data" / "prices"     # price history csv per company

for d in (RAW_DIR, META_DIR, PRICE_DIR):
    d.mkdir(parents=True, exist_ok=True)

REQUEST_DELAY_SECONDS = 2.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)