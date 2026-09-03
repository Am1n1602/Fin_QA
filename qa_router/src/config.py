from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # qa_router/
PROJECT_ROOT = BASE_DIR.parent                               # Financial_Statement_LLM_NLP/

DATA_EXTRACTION_DIR = PROJECT_ROOT / "data_extraction"
DATA_ANALYSIS_DIR = PROJECT_ROOT / "data_analysis"
DATABASE_DIR = PROJECT_ROOT / "database"
RAG_DIR = PROJECT_ROOT / "rag"

DB_PATH = DATABASE_DIR / "data" / "financial_intelligence.db"
RAG_INDEX_DIR = RAG_DIR / "data" / "indices"
EMBEDDING_MODEL_NAME = "all-mpnet-base-v2"
RERANK_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEVICE = "auto"
