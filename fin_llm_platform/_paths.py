from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path:
    override = os.environ.get("FIN_LLM_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _project_root()

DATA_EXTRACTION_DIR = PROJECT_ROOT / "data_extraction"
DATA_ANALYSIS_DIR = PROJECT_ROOT / "data_analysis"
DATABASE_DIR = PROJECT_ROOT / "database"
RAG_DIR = PROJECT_ROOT / "rag"
QA_ROUTER_DIR = PROJECT_ROOT / "qa_router"
LLM_ROUTER_DIR = PROJECT_ROOT / "llm_router"
ORCHESTRATOR_DIR = PROJECT_ROOT / "orchestrator"


def check_layout() -> list[str]:
    """Returns a list of human-readable problems (empty if none) -- used
    by cli.py/pipeline.py to fail with an actionable message instead of
    a raw ModuleNotFoundError when PROJECT_ROOT doesn't actually look
    like the real project (e.g. FIN_LLM_PROJECT_ROOT was set wrong)."""
    problems = []
    for name, path in (
        ("qa_router", QA_ROUTER_DIR),
        ("orchestrator", ORCHESTRATOR_DIR),
    ):
        if not path.is_dir():
            problems.append(f"expected '{name}' directory not found at {path}")
    return problems