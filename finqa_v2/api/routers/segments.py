"""GET /api/v2/companies/{ticker}/segments[/growth] -- per-segment revenue, contribution %
and growth attribution (§12). `segments` goes via the Phase-8 get_segment_data tool;
`segments/growth` isn't a registered tool (§19 doesn't list one), so this calls
SegmentEngine.segment_growth directly -- legitimate for a transport-only REST layer (§30),
distinct from the LLM-facing Tool Registry (§19)."""
from __future__ import annotations

from dataclasses import asdict
from time import perf_counter
from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from finqa_v2.api.deps import TICKER_PATTERN, call_tool, get_engine, get_registry
from finqa_v2.api.models import Basis
from finqa_v2.api.sanitize import strip_server_paths

router = APIRouter(prefix="/api/v2/companies/{ticker}/segments", tags=["segments"])


@router.get("")
def get_segments(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    basis: Basis = "consolidated",
    period: str = "latest_annual",
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_segment_data", ticker=ticker, basis=basis, period=period)


@router.get("/growth")
def segment_growth(
    ticker: str = Path(..., pattern=TICKER_PATTERN),
    basis: Basis = "consolidated",
    kind: Literal["yoy", "qoq"] = "yoy",
    engine=Depends(get_engine),
):
    t0 = perf_counter()
    res = engine.segment_growth(ticker, basis=basis, kind=kind)
    out = asdict(res)
    out["ok"] = res.ok
    out["latency_ms"] = round((perf_counter() - t0) * 1000, 2)
    return strip_server_paths(out)
