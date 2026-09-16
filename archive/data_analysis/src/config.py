from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# data_analysis/ moved into archive/ as a whole unit, but data_extraction/data/ was
# deliberately left at the repo root (finqa_v2's own pipeline reads it directly) --
# climb one extra level past the archive/ wrapper to reach it, rather than assuming
# data_extraction is still BASE_DIR's sibling.
EXTRACTION_PROJECT_DIR = BASE_DIR.parent.parent / "data_extraction"

EXTRACTED_DIR = EXTRACTION_PROJECT_DIR / "data" / "extracted"   # reads canonical JSONs from here
ANALYSIS_OUTPUT_DIR = BASE_DIR / "data" / "analysis"             # writes ratio output here

ANALYSIS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)