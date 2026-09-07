import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

DATA_EXTRACTION_DIR = PROJECT_ROOT / "data_extraction"
DATA_ANALYSIS_DIR = PROJECT_ROOT / "data_analysis"

EXTRACTED_DIR = DATA_EXTRACTION_DIR / "data" / "extracted"      # canonical JSONs (raw facts)
PRICES_DIR = DATA_EXTRACTION_DIR / "data" / "prices"             # price CSVs
ANALYSIS_DIR = DATA_ANALYSIS_DIR / "data" / "analysis"           # ratio/valuation JSONs

DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "financial_intelligence.db"

_UNIVERSE_CACHE_PATH = DATA_EXTRACTION_DIR / "data" / "universe" / "nifty50_constituents.json"

# Fallback for the original pre-Stage-12 6 companies (all IT services --
# accurate, not a guess) when the universe cache hasn't been built yet.
_FALLBACK_COMPANY_METADATA = {
    "TCS": {"name": "Tata Consultancy Services", "sector": "INFORMATION TECHNOLOGY", "bse_scrip": "532540"},
    "INFY": {"name": "Infosys", "sector": "INFORMATION TECHNOLOGY", "bse_scrip": "500209"},
    "HCLTECH": {"name": "HCL Technologies", "sector": "INFORMATION TECHNOLOGY", "bse_scrip": "532281"},
    "WIPRO": {"name": "Wipro", "sector": "INFORMATION TECHNOLOGY", "bse_scrip": "507685"},
    "TECHM": {"name": "Tech Mahindra", "sector": "INFORMATION TECHNOLOGY", "bse_scrip": "532755"},
    "LTM": {"name": "LTIMindtree", "sector": "INFORMATION TECHNOLOGY", "bse_scrip": "540005"},
}


def _load_company_metadata() -> dict[str, dict]:
    if not _UNIVERSE_CACHE_PATH.exists():
        return dict(_FALLBACK_COMPANY_METADATA)
    try:
        payload = json.loads(_UNIVERSE_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(_FALLBACK_COMPANY_METADATA)

    metadata = {
        e["nse_symbol"]: {"name": e["name"], "sector": e.get("sector"), "bse_scrip": e.get("bse_scrip")}
        for e in payload.get("companies", [])
    }

    for symbol, fallback in _FALLBACK_COMPANY_METADATA.items():
        entry = metadata.get(symbol)
        if entry is None:
            continue
        for field, value in fallback.items():
            if not entry.get(field):
                entry[field] = value

    return metadata or dict(_FALLBACK_COMPANY_METADATA)


COMPANY_METADATA = _load_company_metadata()