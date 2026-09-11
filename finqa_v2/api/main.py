"""finqa_v2/api/main.py -- the v2 FastAPI application (§30, §48 Phase 22).

Run it with:
    uvicorn finqa_v2.api.main:app --reload --port 8010

Everything below the lifespan is a thin transport: routers call into the Phase-8 Tool
Registry (deterministic endpoints) or the Phase-10 ReasoningOrchestrator (/qa, /research)
-- no calculation is duplicated here (§30).
"""
from __future__ import annotations

import logging
import time

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from finqa_v2.api import config as api_config
from finqa_v2.api.errors import install_exception_handlers
from finqa_v2.api.routers import (
    companies,
    documents,
    financials,
    growth,
    health,
    qa,
    rankings,
    ratios,
    research,
    search,
    segments,
)
from finqa_v2.observability import (
    configure_logging,
    new_request_id,
    record_http_request,
    refresh_eval_baseline_gauges,
    render_latest,
    request_id_var,
)
from finqa_v2.observability.metrics import CONTENT_TYPE_LATEST

configure_logging()
logger = logging.getLogger("finqa.v2.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from finqa_v2.db import repositories_from_env
    from finqa_v2.engine import FinancialEngine
    from finqa_v2.llm import provider_from_env
    from finqa_v2.reasoning import ReasoningOrchestrator
    from finqa_v2.tools import build_default_registry

    # FINQA_PG_URL/DATABASE_URL in the environment switches this to PostgreSQL
    # (finqa_v2/postgres/repo.py) with no code change -- production deployments run
    # Postgres as its own service; local dev defaults to the bundled SQLite file.
    # Either backend answers each request on a different worker thread from one
    # connection built here, so both wrap that connection in their own internal lock
    # (_ThreadSafeConnection / _PgConn) rather than opening one per request.
    repos = repositories_from_env(sqlite_path=api_config.DB_PATH, check_same_thread=False)
    logger.info("Repositories ready (%s).", type(repos).__name__)
    engine = FinancialEngine(repos)

    retriever = None
    if not api_config.NO_RETRIEVER:
        try:
            from finqa_v2.retrieval.evaluate import build_retriever

            retriever = build_retriever(repos, bm25_path=api_config.BM25_PATH,
                                        vector_dir=api_config.VECTOR_DIR)
            logger.info("Retriever ready, modes=%s", retriever.modes)
        except Exception:
            logger.exception("Could not build the retriever -- /search and document "
                             "evidence in /qa will be unavailable; other endpoints unaffected.")

    registry = build_default_registry(repos, engine=engine, retriever=retriever)
    provider = provider_from_env()
    orchestrator = ReasoningOrchestrator(repos, registry=registry, provider=provider,
                                        retriever=retriever, engine=engine)

    app.state.repos = repos
    app.state.engine = engine
    app.state.retriever = retriever
    app.state.registry = registry
    app.state.provider = provider
    app.state.orchestrator = orchestrator
    logger.info("finqa_v2 API ready (llm_provider=%s).", getattr(provider, "name", "null"))

    try:
        yield
    finally:
        repos.close()


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="Fin_QA v2 API",
    description="The v2 research architecture over FastAPI: deterministic financial "
                "metrics/ratios/growth/segments/rankings, hybrid document search, and "
                "evidence-grounded, verified natural-language QA over the NIFTY 50. Every "
                "number comes from the Financial Engine -- this API computes nothing itself.",
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


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """Tags every log line emitted while handling this request with the same
    request_id (Phase 25's "tracing" for a single-service deployment -- grep/query
    one id to see a request's full path through the API, Tool Registry, and LLM
    provider), and records HTTP-level Prometheus metrics keyed by the route's path
    TEMPLATE (e.g. `/api/v2/companies/{ticker}`, not `/api/v2/companies/TCS`) so a
    ticker doesn't become a distinct metric series per company."""
    request_id = new_request_id()
    token = request_id_var.set(request_id)
    t0 = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        path = route.path if route is not None else request.url.path
        record_http_request(request.method, path, status_code, time.perf_counter() - t0)
        request_id_var.reset(token)


install_exception_handlers(app)

app.include_router(health.router)
app.include_router(companies.router)
app.include_router(financials.router)
app.include_router(ratios.router)
app.include_router(growth.router)
app.include_router(segments.router)
app.include_router(rankings.router)
app.include_router(documents.router)
app.include_router(search.router)
app.include_router(research.router)
app.include_router(qa.router)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus scrape target: HTTP/tool/LLM/verification counters and histograms
    recorded from the choke points they already flow through, plus the pinned
    regression-gate baseline's accuracy numbers (refreshed from disk on every scrape,
    so updating the pinned baseline shows up here without an API restart)."""
    refresh_eval_baseline_gauges(api_config.EVAL_BASELINE_PATH)
    return Response(content=render_latest(), media_type=CONTENT_TYPE_LATEST)


def run() -> None:
    """Entry point for the `finqa-api-v2` console script (see pyproject.toml)."""
    import uvicorn

    uvicorn.run("finqa_v2.api.main:app", host=api_config.HOST, port=api_config.PORT, reload=False)


if __name__ == "__main__":
    run()
