"""
api/errors.py -- turns every exception this API can hit into a small, actionable
JSON body instead of a raw traceback, just returned as HTTP responses instead of printed to a terminal.

Response shape, always:
    {"error": "<short machine-readable code>", "detail": "<human-readable message>"}

The full traceback is still logged server-side (via FastAPI/uvicorn's normal
logging of the handled exception) -- it's just never sent to the client.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("finqa.api")


class ApiError(Exception):
    """Base class for errors this API raises deliberately (as opposed to
    exceptions bubbling up from the engine/bridges below it)."""

    status_code = 500
    error_code = "internal_error"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class CompanyNotFoundError(ApiError):
    status_code = 404
    error_code = "company_not_found"

    def __init__(self, symbol: str):
        super().__init__(f"No company with symbol '{symbol}' in the database.")
        self.symbol = symbol


class EngineNotReadyError(ApiError):
    """Raised by api/deps.py when a request arrives before app startup has
    finished initializing the analysis/RAG bridges (should be rare -- FastAPI
    doesn't serve requests until the lifespan startup phase completes -- but
    cheaper to guard than to assume)."""

    status_code = 503
    error_code = "engine_not_ready"


def _engine_error_detail(exc: RuntimeError) -> str:
    text = str(exc)
    if "worker exited unexpectedly" in text or "worker error on" in text:
        return (
            f"The analysis/RAG engine reported an internal error: {text} "
            f"Check the API server's own stderr/logs for the underlying traceback "
            f"printed directly by that worker process."
        )
    return f"Engine error: {text}"


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.error_code, "detail": exc.detail})

    @app.exception_handler(RuntimeError)
    async def _runtime_error_handler(request: Request, exc: RuntimeError):
        # This is the exception class AnalysisBridge/RagBridge raise on a
        # worker crash or protocol mismatch -- see qa_router/src/bridges/*.
        logger.exception("Engine RuntimeError handling %s %s", request.method, request.url.path)
        return JSONResponse(status_code=502, content={"error": "engine_error", "detail": _engine_error_detail(exc)})

    @app.exception_handler(sqlite3.OperationalError)
    async def _sqlite_error_handler(request: Request, exc: sqlite3.OperationalError):
        logger.exception("SQLite error handling %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=503,
            content={
                "error": "database_unavailable",
                "detail": "Could not read the database. Check FINQA_DB_PATH points at a real, "
                          "unlocked financial_intelligence.db and that no other process (e.g. the "
                          "orchestrator's scheduled pipeline run) has it open exclusively right now. "
                          "See the server's own logs for the exact SQLite error.",
            },
        )

    @app.exception_handler(FileNotFoundError)
    async def _file_not_found_handler(request: Request, exc: FileNotFoundError):
        logger.exception("Missing file/dir handling %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=503,
            content={
                "error": "data_not_ready",
                "detail": "A required data file or folder is missing on the server. This usually "
                          "means the ingestion/analysis pipeline hasn't been run yet for this data "
                          "(or, in the demo deployment, that the prebuilt dataset wasn't uploaded to "
                          "the expected path). See the server's own logs for which file.",
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception handling %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": f"Something went wrong ({type(exc).__name__}). Full details were written to "
                          f"the server's own logs.",
            },
        )