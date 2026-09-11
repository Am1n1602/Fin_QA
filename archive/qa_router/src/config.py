from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # archive/qa_router/
PROJECT_ROOT = BASE_DIR.parent                               # archive/
_REPO_ROOT = PROJECT_ROOT.parent                             # true repo root

# data_analysis/ and rag/ moved wholesale into archive/ alongside qa_router/, so
# they're still genuinely siblings here. database/data/ was deliberately left at the
# repo root when database/src/ moved (finqa_v2's own pipeline reads it directly).
DATA_EXTRACTION_DIR = PROJECT_ROOT / "data_extraction"
DATA_ANALYSIS_DIR = PROJECT_ROOT / "data_analysis"
DATABASE_DIR = _REPO_ROOT / "database"
RAG_DIR = PROJECT_ROOT / "rag"

DB_PATH = DATABASE_DIR / "data" / "financial_intelligence.db"
RAG_INDEX_DIR = RAG_DIR / "data" / "indices"
EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEVICE = "auto"
