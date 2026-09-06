"""GET /companies/{symbol}/trends -- historical trend analysis, delegating
to data_analysis via the same AnalysisBridge subprocess qa_router uses
(see qa_router/src/qa.py's _handle_trend())."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_analysis_bridge, get_db_path, require_api_key, resolve_company
from api.models import FilingType

router = APIRouter(prefix="/companies/{symbol}/trends", tags=["trends"],
                    dependencies=[Depends(require_api_key)])


@router.get("")
def get_trends(
    symbol: str,
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    company = resolve_company(symbol, db_path)
    result = analysis_bridge.analyze_trends(company["symbol"], filing_type)
    return {"symbol": company["symbol"], "filing_type": filing_type, **result}