"""
api/main.py -- the `finqa-api` FastAPI application.

Run it with:
    finqa-api                              # after `pip install -e .`
    uvicorn api.main:app --reload           # equivalent, for local dev

"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api._paths import QA_ROUTER_DIR, check_layout

_layout_problems = check_layout()
if _layout_problems:
    raise RuntimeError(
        "finqa-api: " + "; ".join(_layout_problems) + ". This must be run from an editable install "
        "(`pip install -e .` from the project root) with qa_router/ still present alongside api/ -- "
        "see MANUAL.md."
    )

sys.path.insert(0, str(QA_ROUTER_DIR))

# --- everything below this line may safely import from `src.*` (qa_router's package) ---

from src.bridges.analysis_bridge import AnalysisBridge  # noqa: E402
from src.bridges.rag_bridge import RagBridge  # noqa: E402
from src.config import (  # noqa: E402
    DATA_ANALYSIS_DIR, DB_PATH, DEVICE, EMBEDDING_MODEL_NAME, RAG_DIR, RAG_INDEX_DIR, RERANK_MODEL_NAME,
)

from api import config as api_config  # noqa: E402
from api.errors import install_exception_handlers  # noqa: E402
from api.routers import companies, financials, health, peers, qa, ranking, ratios, reports, sectors, trends  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("finqa.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("FINQA_DB_PATH", str(DB_PATH))
    analysis_bridge = AnalysisBridge(db_path=db_path, data_analysis_dir=str(DATA_ANALYSIS_DIR))

    app.state.db_path = db_path
    app.state.analysis_bridge = analysis_bridge
    app.state.rag_bridge = None
    app.state.rag_ready = False

    loop = asyncio.get_event_loop()

    logger.info("Starting analysis engine subprocess (db_path=%s)...", db_path)
    # AnalysisBridge's worker just imports data_analysis's own modules
    # (pandas etc.) -- quick. Block startup on this one; every read/analytics
    # endpoint in this API needs it.
    await loop.run_in_executor(None, analysis_bridge.warm_up)
    logger.info("Analysis engine ready -- now serving requests.")


    rag_bridge = None
    if api_config.RAG_DISABLED:
        logger.info(
            "FINQA_DISABLE_RAG is set -- RAG engine will NOT be started. Narrative/"
            "regulatory-disclosure/complex questions will return a clean 'not available' "
            "answer instead of loading the embedding/reranker models."
        )
    else:
        rag_bridge = RagBridge(
            db_path=db_path, rag_dir=str(RAG_DIR), index_dir=str(RAG_INDEX_DIR),
            model_name=EMBEDDING_MODEL_NAME, rerank_model=RERANK_MODEL_NAME, device=DEVICE,
        )
        app.state.rag_bridge = rag_bridge

        def _warm_up_rag() -> None:
            rag_bridge.warm_up()
            app.state.rag_ready = True
            logger.info("RAG engine ready (embedding/rerank models loaded).")

        app.state.rag_warmup_future = loop.run_in_executor(None, _warm_up_rag)

    try:
        yield
    finally:
        logger.info("Shutting down engine subprocesses...")
        analysis_bridge.close()
        if rag_bridge is not None:
            rag_bridge.close()


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="Fin_QA API",
    description="Deterministic financial metrics, peer comparison, ranking, financial health, and "
                 "RAG-grounded natural-language QA over NIFTY 50 filings. Every number comes from the "
                 "existing calculation engine -- this API computes nothing itself.",
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=api_config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

install_exception_handlers(app)

app.include_router(companies.router)
app.include_router(financials.router)
app.include_router(ratios.router)
app.include_router(trends.router)
app.include_router(peers.router)
app.include_router(ranking.router)
app.include_router(health.router)
app.include_router(reports.router)
app.include_router(sectors.router)
app.include_router(qa.router)


@app.get("/health", tags=["meta"])
def liveness() -> dict:
    """This API server's own liveness/readiness check -- not a company's
    financial health (that's GET /companies/{symbol}/health).

    A cheap, always-fast check that the process is up and which engines have
    finished warming up. For a stricter "is it actually safe to send this
    demo real traffic" signal (data files present, not just process alive),
    see GET /ready below -- see also "Fin_QA -- ZeroCost Demo Deployment
    Roadmap.md" sections 17-18, which specify both endpoints separately."""
    analysis_ready = getattr(app.state, "analysis_bridge", None) is not None
    rag_ready = getattr(app.state, "rag_ready", False)
    return {
        "status": "ok" if analysis_ready else "starting",
        "mode": api_config.FINQA_MODE,
        "analysis_engine_ready": analysis_ready,
        "rag_engine_enabled": not api_config.RAG_DISABLED,
        "rag_engine_ready": rag_ready,
        "note": "rag_engine_ready only matters for narrative/complex questions -- numeric facts, "
                "ratios, trends, peer comparison, rankings, financial health, and reports never use it, "
                "and work as soon as analysis_engine_ready is true. When rag_engine_enabled is false "
                "(FINQA_DISABLE_RAG), those questions return a clean 'not available' answer instead "
                "of ever trying to load the RAG engine.",
    }


@app.get("/ready", tags=["meta"])
def readiness() -> dict:

    analysis_ready = getattr(app.state, "analysis_bridge", None) is not None
    rag_ready = getattr(app.state, "rag_ready", False)
    db_path = getattr(app.state, "db_path", None)
    database_ok = bool(db_path) and Path(db_path).is_file()
    # A deliberately-disabled RAG engine (FINQA_DISABLE_RAG) should never block
    # overall readiness -- it's never going to become ready, by design.
    rag_ok = rag_ready or api_config.RAG_DISABLED
    ready = analysis_ready and database_ok and rag_ok
    return {
        "ready": ready,
        "mode": api_config.FINQA_MODE,
        "database": database_ok,
        "rag_enabled": not api_config.RAG_DISABLED,
        "faiss": rag_ready,
        "bm25": rag_ready,
        "models": rag_ready,
    }


def run() -> None:
    """Entry point for the `finqa-api` console script (see pyproject.toml)."""
    import uvicorn

    uvicorn.run("api.main:app", host=api_config.HOST, port=api_config.PORT, reload=False)


if __name__ == "__main__":
    run()