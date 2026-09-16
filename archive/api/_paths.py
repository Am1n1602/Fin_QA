from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path:
    override = os.environ.get("FIN_LLM_PROJECT_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _project_root()
QA_ROUTER_DIR = PROJECT_ROOT / "qa_router"


def check_layout() -> list[str]:
    """Returns a list of human-readable problems (empty if none). api/main.py
    checks this before doing the sys.path insertion + import that the whole
    app depends on, so a missing sibling folder fails once, loudly, and
    legibly at startup instead of as a buried ModuleNotFoundError from deep
    inside a route handler."""
    problems = []
    if not QA_ROUTER_DIR.is_dir():
        problems.append(f"expected 'qa_router' directory not found at {QA_ROUTER_DIR}")
    return problems