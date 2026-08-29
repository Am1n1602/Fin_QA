from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EXTRACTION_PROJECT_DIR = BASE_DIR.parent / "data_extraction"

EXTRACTED_DIR = EXTRACTION_PROJECT_DIR / "data" / "extracted"   # reads canonical JSONs from here
ANALYSIS_OUTPUT_DIR = BASE_DIR / "data" / "analysis"             # writes ratio output here

ANALYSIS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)