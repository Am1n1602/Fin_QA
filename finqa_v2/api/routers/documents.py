"""GET /api/v2/companies/{ticker}/documents/{section}, /api/v2/sources/{document_id} --
filing passages by section, and one citation's provenance detail (§13/§18), via the
Phase-8 get_document_section/get_source tools."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from finqa_v2.api.deps import call_tool, get_registry

router = APIRouter(prefix="/api/v2", tags=["documents"])


@router.get("/companies/{ticker}/documents/{section}")
def get_document_section(
    ticker: str,
    section: str,
    financial_year: int | None = None,
    limit: int = Query(8, ge=1, le=40),
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_document_section", company=ticker, section=section,
                     financial_year=financial_year, limit=limit)


@router.get("/sources/{document_id}")
def get_source(
    document_id: int,
    page: int | None = None,
    page_end: int | None = None,
    section: str | None = None,
    registry=Depends(get_registry),
):
    return call_tool(registry, "get_source", document_id=document_id, page=page,
                     page_end=page_end, section=section)
