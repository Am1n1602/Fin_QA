"""GET /api/v2/health -- this API server's own liveness/readiness, not a company's
financial health."""
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["meta"])


@router.get("/health")
def health(request: Request) -> dict:
    st = request.app.state
    repos_ready = getattr(st, "repos", None) is not None
    engine_ready = getattr(st, "engine", None) is not None
    retriever = getattr(st, "retriever", None)
    provider = getattr(st, "provider", None)
    return {
        "status": "ok" if (repos_ready and engine_ready) else "starting",
        "db_ready": repos_ready,
        "engine_ready": engine_ready,
        "retriever_modes": list(retriever.modes) if retriever is not None else [],
        "llm_provider": getattr(provider, "name", "null") if provider else "null",
        "note": "llm_provider='null' means /qa and /research still work, using the "
                "deterministic (no-LLM) synthesis path -- numeric/ratio/growth/segment/"
                "ranking endpoints never need an LLM.",
    }
