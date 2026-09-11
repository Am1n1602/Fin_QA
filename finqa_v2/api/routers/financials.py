"""GET /api/v2/companies/{ticker}/financials -- a raw or derived metric (§11), via the
Phase-8 get_metric tool. Never recomputed here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from finqa_v2.api.deps import call_tool, get_registry
from finqa_v2.api.models import Basis

router = APIRouter(prefix="/api/v2/companies/{ticker}/financials", tags=["financials"])


@router.get("")
def get_financials(
    ticker: str,
    metric: str = Query(..., description="canonical or derived metric, e.g. revenue, ebitda"),
    basis: Basis = "consolidated",
    period: str = Query("latest", description="'latest' | 'latest_annual' | 'FY2026' | 'FY2026Q1'"),
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_metric", ticker=ticker, metric=metric, basis=basis, period=period)
