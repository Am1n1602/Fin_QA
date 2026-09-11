"""GET /api/v2/companies/{ticker}/ratios[, /decompose] -- ROE/ROCE/margins/valuation
(§11/§15) and DuPont/net-margin decomposition (§11), via the Phase-8 tools."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from finqa_v2.api.deps import TICKER_PATTERN, call_tool, get_registry
from finqa_v2.api.models import Basis

router = APIRouter(prefix="/api/v2/companies/{ticker}/ratios", tags=["ratios"])


@router.get("")
def get_ratio(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    ratio: str = Query(..., description="roe, roce, ebitda_margin, debt_to_equity, pe, pb, ..."),
    basis: Basis = "consolidated",
    # See financials.py: default is the latest ANNUAL period, not the engine's bare
    # "latest" (usually a quarter), so an omitted period doesn't silently understate a
    # ratio like ROE by ~4x.
    period: str = "latest_annual",
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_ratio", ticker=ticker, ratio=ratio, basis=basis, period=period)


@router.get("/decompose")
def decompose(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    metric: Literal["roe", "dupont", "net_margin", "net_profit_margin"] = "roe",
    basis: Basis = "consolidated",
    period: str = "latest_annual",
    registry=Depends(get_registry),
):
    return call_tool(registry, "decompose_metric", ticker=ticker, metric=metric, basis=basis, period=period)
