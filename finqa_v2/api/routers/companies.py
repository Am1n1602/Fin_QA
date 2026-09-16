"""GET /api/v2/companies, /companies/{ticker}, /companies/{ticker}/peers -- thin wrappers
over the Phase-8 get_index_members/get_company/get_peers tools."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from finqa_v2.api.deps import TICKER_PATTERN, call_tool, get_registry

router = APIRouter(prefix="/api/v2/companies", tags=["companies"])


@router.get("")
def list_companies(
    index: str = Query("NIFTY 50", description="Index name"),
    on: str | None = Query(None, description="ISO date; omit for current members"),
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_index_members", index_name=index, on=on)


@router.get("/{ticker}")
def get_company(ticker: str = Path(..., pattern=TICKER_PATTERN), registry=Depends(get_registry)):
    return call_tool(registry, "get_company", ticker=ticker)


@router.get("/{ticker}/peers")
def get_peers(ticker: str = Path(..., pattern=TICKER_PATTERN),
             limit: int = Query(15, ge=1, le=60), registry=Depends(get_registry)):
    return call_tool(registry, "get_peers", ticker=ticker, limit=limit)
