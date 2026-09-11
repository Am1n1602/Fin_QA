"""GET /api/v2/rankings -- order a set of companies by one metric/ratio (§11), via the
Phase-8 compare_companies tool."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from finqa_v2.api.deps import call_tool, get_registry
from finqa_v2.api.models import Basis

router = APIRouter(prefix="/api/v2/rankings", tags=["rankings"])


@router.get("")
def rankings(
    metric: str = Query(..., description="a metric or ratio name, e.g. roe, revenue"),
    tickers: str = Query(..., description="comma-separated NSE tickers"),
    basis: Basis = "consolidated",
    # See financials.py: default is the latest ANNUAL period, not the engine's bare
    # "latest" (usually a quarter), so an omitted period doesn't silently understate a
    # ratio like ROE by ~4x.
    period: str = "latest_annual",
    registry=Depends(get_registry),
):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    return call_tool(registry, "compare_companies", metric=metric, tickers=ticker_list,
                     basis=basis, period=period)
