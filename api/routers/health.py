"""GET /companies/{symbol}/health -- financial health (Piotroski F-Score,
partial Altman Z), delegating to data_analysis via AnalysisBridge (see
qa_router/src/qa.py's _handle_financial_health()).

Not to be confused with GET /health at the app root, which is this API
server's own liveness check -- see api/main.py."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import get_analysis_bridge, get_db_path, require_api_key, resolve_company
from api.models import FilingType

router = APIRouter(prefix="/companies/{symbol}/health", tags=["financial-health"],
                    dependencies=[Depends(require_api_key)])


@router.get("")
def get_financial_health(
    symbol: str,
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    company = resolve_company(symbol, db_path)
    result = analysis_bridge.compute_financial_health(company["symbol"], filing_type)
    return {
        "symbol": company["symbol"],
        "filing_type": filing_type,
        **result,
        "caveats": [
            "Piotroski is 8 of 9 criteria -- Delta Gross Margin excluded (no clean COGS tag for "
            "Ind AS IT-services filings), not scored as failing.",
            "Altman partial_z uses only X1/X3/X4 -- not the official Z''-Score; its published "
            "2.6/1.1 thresholds do not apply.",
        ],
    }