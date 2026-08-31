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

COMPANY_NAMES = {
    "TCS": "Tata Consultancy Services",
    "INFY": "Infosys",
    "HCLTECH": "HCL Technologies",
}
