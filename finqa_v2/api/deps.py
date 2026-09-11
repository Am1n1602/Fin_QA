"""FastAPI dependency-injection helpers: pull the long-lived repos/engine/retriever/
registry/orchestrator built once at startup (see main.py's lifespan) out of app.state,
and the one generic tool-call -> HTTP-response bridge every deterministic router uses.
See docs/file-guide.md.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import Request

from finqa_v2.api.errors import ApiError, CompanyNotFoundError, EngineNotReadyError
from finqa_v2.api.sanitize import strip_server_paths


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


def get_retriever(request: Request):
    """May legitimately be None (FINQA_V2_NO_RETRIEVER=1, or no BM25 index built) --
    callers that need one raise their own error; /search does."""
    return getattr(request.app.state, "retriever", None)


def resolve_company(repos, ticker: str):
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
# a tiny per-client-IP rate limiter for the one route where an LLM may run
# --------------------------------------------------------------------------- #
_RATE_LIMIT_WINDOW_S = 60.0
_rate_limit_lock = Lock()
_rate_limit_hits: dict[str, deque] = defaultdict(deque)


def rate_limit_qa(request: Request) -> None:
    import os

    # read directly (not the frozen api_config constant) so tests can patch os.environ
    # without needing to reload the config module.
    limit = int(os.environ.get("FINQA_V2_QA_RATE_LIMIT", "10"))
    if limit <= 0:
        return
    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_limit_lock:
        hits = _rate_limit_hits[client_ip]
        while hits and now - hits[0] >= _RATE_LIMIT_WINDOW_S:
            hits.popleft()
        if len(hits) >= limit:
            err = ApiError(f"Too many questions from this client -- this API allows {limit} per minute.")
            err.status_code, err.error_code = 429, "rate_limited"
            raise err
        hits.append(now)


def require_api_key(request: Request) -> None:
    import os

    key = os.environ.get("FINQA_V2_API_KEY", "")
    if not key:
        return
    header = "X-API-Key"
    if request.headers.get(header) != key:
        err = ApiError(f"Missing or invalid API key (expected in the {header} header).")
        err.status_code, err.error_code = 401, "unauthorized"
        raise err
