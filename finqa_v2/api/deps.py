"""FastAPI dependency-injection helpers: pull the long-lived repos/engine/retriever/
registry/orchestrator built once at startup (see main.py's lifespan) out of app.state,
and the one generic tool-call -> HTTP-response bridge every deterministic router uses.
See docs/file-guide.md.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from finqa_v2.api.errors import ApiError, CompanyNotFoundError, EngineNotReadyError
from finqa_v2.api.sanitize import strip_server_paths

# Every real NSE ticker in the universe fits this (incl. "M&M", "BAJAJ-AUTO"). Exported
# so routers can enforce it directly on the path parameter via `Path(pattern=...)`,
# which rejects a malformed ticker with FastAPI's own 422 before the route body (and
# therefore the tool call) ever runs.
TICKER_PATTERN = r"^[A-Za-z0-9&.\-]{1,20}$"
_TICKER_RE = re.compile(TICKER_PATTERN)


def _state(request: Request, name: str, message: str):
    val = getattr(request.app.state, name, None)
    if val is None:
        raise EngineNotReadyError(message)
    return val


def get_repos(request: Request):
    return _state(request, "repos", "The database has not finished initialising yet -- try again shortly.")


def get_engine(request: Request):
    return _state(request, "engine", "The financial engine has not finished initialising yet -- try again shortly.")


def get_registry(request: Request):
    return _state(request, "registry", "The tool registry has not finished initialising yet -- try again shortly.")


def get_orchestrator(request: Request):
    return _state(request, "orchestrator",
                 "The reasoning engine has not finished initialising yet -- try again shortly.")


def get_qa_cache(request: Request):
    return _state(request, "qa_cache", "The answer cache has not finished initialising yet -- try again shortly.")


def get_research_cache(request: Request):
    return _state(request, "research_cache",
                 "The answer cache has not finished initialising yet -- try again shortly.")


def get_retriever(request: Request):
    """May legitimately be None (FINQA_V2_NO_RETRIEVER=1, or no BM25 index built) --
    callers that need one raise their own error; /search does."""
    return getattr(request.app.state, "retriever", None)


def resolve_company(repos, ticker: str):
    # Reject obviously-malformed input before it ever reaches a query (every ticker
    # query is already parameterized, so this isn't closing an injection hole -- it's
    # honest input validation: a garbage ticker gets a clean 422 instead of a DB round
    # trip that was always going to end in "not found" anyway).
    if not _TICKER_RE.match(ticker):
        err = ApiError(f"{ticker!r} is not a valid ticker (expected 1-20 characters: "
                       f"letters, digits, '&', '.', or '-').")
        err.status_code, err.error_code = 422, "invalid_ticker"
        raise err
    c = repos.companies.resolve(ticker)
    if c is None:
        raise CompanyNotFoundError(ticker)
    return c


def call_tool(registry, name: str, **kwargs) -> dict:
    """Run a Phase-8 tool and turn its ToolResult into the public response shape every
    deterministic router returns: the tool's value dict, plus `evidence` and
    `latency_ms`, with any server-side path stripped (§ Phase 22 -- Citation.uri)."""
    res = registry.call(name, **kwargs)
    if not res.ok:
        message = res.error or "tool call failed"
        if message.startswith("invalid input"):
            status, code = 422, "invalid_input"
        elif message.startswith("LookupError"):
            status, code = 404, "not_found"
        elif message.startswith("RuntimeError") and "retriever" in message:
            status, code = 503, "retriever_not_ready"
        else:
            status, code = 502, "tool_error"
        err = ApiError(message)
        err.status_code, err.error_code = status, code
        raise err
    payload = res.value if isinstance(res.value, dict) else {"value": res.value}
    out = {**payload, "evidence": list(res.evidence), "latency_ms": round(res.latency_ms, 2)}
    return strip_server_paths(out)


# --------------------------------------------------------------------------- #
# per-client-IP sliding-window rate limiting (§26) -- two independent limiters:
# a generous one applied to EVERY route (security_middleware, main.py) and a much
# stricter one that only /qa and /research additionally apply on top, since those are
# the routes an LLM call (real cost, real latency) may run on.
# --------------------------------------------------------------------------- #
_RATE_LIMIT_WINDOW_S = 60.0


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, client_ip: str, limit: int) -> bool:
        """Records the hit and returns True if under `limit` hits in the trailing
        window; returns True without recording anything if `limit` is 0 or negative
        (the "disabled" convention every FINQA_V2_*_RATE_LIMIT env var shares)."""
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client_ip]
            while hits and now - hits[0] >= _RATE_LIMIT_WINDOW_S:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


_qa_limiter = _SlidingWindowLimiter()
_general_limiter = _SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit_qa(request: Request) -> None:
    import os

    # read directly (not a frozen api_config constant) so tests can patch os.environ
    # without needing to reload the config module.
    limit = int(os.environ.get("FINQA_V2_QA_RATE_LIMIT", "10"))
    if not _qa_limiter.allow(_client_ip(request), limit):
        err = ApiError(f"Too many questions from this client -- this API allows {limit} per minute.")
        err.status_code, err.error_code = 429, "rate_limited"
        raise err


def check_general_rate_limit(request: Request) -> str | None:
    """Pure check (returns a message instead of raising) for `security_middleware`
    (main.py), which runs OUTSIDE FastAPI's exception-handler pipeline -- an exception
    raised here would surface as a raw, unhandled 500, not a clean JSON error response."""
    import os

    limit = int(os.environ.get("FINQA_V2_RATE_LIMIT", "120"))
    if not _general_limiter.allow(_client_ip(request), limit):
        return f"Too many requests from this client -- this API allows {limit} per minute."
    return None


def check_api_key(request: Request) -> str | None:
    """Pure check (returns a message instead of raising), for the same reason as
    `check_general_rate_limit` above -- both back `security_middleware`."""
    import os

    key = os.environ.get("FINQA_V2_API_KEY", "")
    if not key:
        return None
    if request.headers.get("X-API-Key") != key:
        return "Missing or invalid API key (expected in the X-API-Key header)."
    return None
