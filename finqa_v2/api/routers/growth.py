"""GET /api/v2/companies/{ticker}/growth[/cagr] -- YoY/QoQ growth and CAGR (§11), via the
Phase-8 get_growth/get_cagr tools."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from finqa_v2.api.deps import TICKER_PATTERN, call_tool, get_registry
from finqa_v2.api.models import Basis

router = APIRouter(prefix="/api/v2/companies/{ticker}/growth", tags=["growth"])


@router.get("")
def get_growth(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    metric: str = Query(..., description="canonical or derived metric, e.g. revenue, net_profit"),
    kind: Literal["yoy", "qoq"] = "yoy",
    basis: Basis = "consolidated",
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_growth", ticker=ticker, metric=metric, kind=kind, basis=basis)


@router.get("/cagr")
def get_cagr(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    metric: str = Query(...),
    basis: Basis = "consolidated",
    years: float | None = None,
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_cagr", ticker=ticker, metric=metric, basis=basis, years=years)
