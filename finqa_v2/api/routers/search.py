"""GET /api/v2/search -- hybrid retrieval over filing text (§16), via the Phase-8
search_documents tool."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from finqa_v2.api.deps import call_tool, get_registry

router = APIRouter(prefix="/api/v2/search", tags=["search"])


@router.get("")
def search(
    q: str = Query(..., min_length=2, alias="q"),
    company: str | None = Query(None, description="NSE ticker to scope the search to"),
    section: list[str] | None = Query(None, description="restrict to these chunk sections"),
    financial_year: int | None = None,
    k: int = Query(5, ge=1, le=20),
    mode: Literal["lexical", "vector", "hybrid"] = "hybrid",
    registry=Depends(get_registry),
):
    return call_tool(registry, "search_documents", query=q, company=company,
                     sections=section, financial_year=financial_year, k=k, mode=mode)
