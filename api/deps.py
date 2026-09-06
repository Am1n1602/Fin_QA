"""
api/deps.py -- FastAPI dependency-injection helpers.

Import order matters here: this module does `from src...` imports (qa_router's
own package), which only resolve once api/main.py has put qa_router/ on
sys.path. main.py does that insertion before it imports this module or any
router module -- see main.py's own comment on this. Don't import api.deps (or
any api.routers.* module) from anywhere that runs before main.py's sys.path
insertion.
"""

from __future__ import annotations

from fastapi import Header, Request

from src.database_ro import list_companies, sector_peers as _sector_peers

from api import config as api_config
from api.errors import ApiError, CompanyNotFoundError, EngineNotReadyError


class UnauthorizedError(ApiError):
    status_code = 401
    error_code = "unauthorized"


def require_api_key(x_api_key: str | None = Header(default=None, alias=api_config.API_KEY_HEADER)) -> None:
    """No-op when FINQA_API_KEY isn't set (the default -- local/dev use).
    Once set, every request must echo it back in the X-API-Key header."""
    if not api_config.API_KEY:
        return
    if x_api_key != api_config.API_KEY:
        raise UnauthorizedError("Missing or invalid API key (expected in the X-API-Key header).")


def get_db_path(request: Request) -> str:
    return request.app.state.db_path


def get_analysis_bridge(request: Request):
    bridge = getattr(request.app.state, "analysis_bridge", None)
    if bridge is None:
        raise EngineNotReadyError("The analysis engine has not finished starting up yet -- try again shortly.")
    return bridge


def get_rag_bridge(request: Request):
    bridge = getattr(request.app.state, "rag_bridge", None)
    if bridge is None:
        raise EngineNotReadyError("The RAG engine has not finished starting up yet -- try again shortly.")
    return bridge


def resolve_company(symbol: str, db_path: str) -> dict:
    """Case-insensitive symbol lookup against the companies table. Raises
    CompanyNotFoundError (-> HTTP 404) rather than letting every downstream
    query silently return empty results for a typo'd symbol."""
    wanted = symbol.strip().upper()
    for row in list_companies(db_path):
        if row["symbol"].upper() == wanted:
            return row
    raise CompanyNotFoundError(symbol)


def parse_symbol_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def default_peer_group(db_path: str, symbol: str) -> tuple[list[str], str | None]:
    """The default peer group for /peers, /rankings, and /report when the
    caller didn't pass explicit peer symbols: same-sector companies (via
    qa_router's own src.database_ro.sector_peers()) when `symbol`'s sector
    is known, else the whole universe as a fallback. Mirrors qa_router/src/
    qa.py's _peer_universe() -- see that function's docstring for the full
    reasoning (comparing a bank's ROE against an oil & gas company's isn't
    a peer comparison).

    Returns (peer_symbols, sector_or_None) -- sector is None exactly when
    the whole-universe fallback was used, so callers can say so in the
    response instead of silently comparing across sectors."""
    peers, sector = _sector_peers(db_path, symbol)
    if sector:
        return peers, sector
    return [c["symbol"] for c in list_companies(db_path) if c["symbol"] != symbol], None