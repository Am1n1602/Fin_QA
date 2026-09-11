"""GET /api/v2/companies/{ticker}/financials -- a raw or derived metric (§11), via the
Phase-8 get_metric tool. Never recomputed here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from finqa_v2.api.deps import TICKER_PATTERN, call_tool, get_registry
from finqa_v2.api.models import Basis

router = APIRouter(prefix="/api/v2/companies/{ticker}/financials", tags=["financials"])


@router.get("")
def get_financials(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    metric: str = Query(..., description="canonical or derived metric, e.g. revenue, ebitda"),
    basis: Basis = "consolidated",
    # Default is "latest_annual", not the engine's own "latest" (= the single most-recent
    # period record, almost always a QUARTER for an actively-quarterly-filing company --
    # an unannualised figure that looks plausible but is wrong for anyone who omits period).
    period: str = Query("latest_annual", description="'latest_annual' | 'latest' | 'FY2026' | 'FY2026Q1'"),
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_metric", ticker=ticker, metric=metric, basis=basis, period=period)
