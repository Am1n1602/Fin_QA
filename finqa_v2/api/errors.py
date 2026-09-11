"""Turns every exception this API can hit into `{"error": <code>, "detail": <message>}`
instead of a raw traceback. See docs/file-guide.md.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("finqa.v2.api")


class ApiError(Exception):
    status_code = 500
    error_code = "internal_error"

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class CompanyNotFoundError(ApiError):
    status_code = 404
    error_code = "company_not_found"

    def __init__(self, ticker: str):
        super().__init__(f"No company with ticker '{ticker}' in the database.")
        self.ticker = ticker


class EngineNotReadyError(ApiError):
    """The lifespan startup hasn't finished building repos/engine/retriever yet."""

    status_code = 503
    error_code = "engine_not_ready"


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.error_code, "detail": exc.detail})

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception handling %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error",
                    "detail": f"Something went wrong ({type(exc).__name__}). See the server's own logs."},
        )
