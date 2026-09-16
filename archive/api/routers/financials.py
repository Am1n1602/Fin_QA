"""GET /companies/{symbol}/financials -- raw, as-extracted XBRL facts
(financial_facts table). These are never recomputed here -- see
qa_router/src/qa.py's own warning about financial_facts values being
reported exactly as extracted, with no separately-tracked unit/scale."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.database_ro import fact_history, latest_fact
from src.metrics import METRICS

from archive.api.deps import get_db_path, require_api_key, resolve_company
from archive.api.models import FilingType

router = APIRouter(prefix="/companies/{symbol}/financials", tags=["financials"],
                    dependencies=[Depends(require_api_key)])


_DEFAULT_FACT_FIELDS = [m.field for m in METRICS if m.table == "financial_facts"]


@router.get("")
def get_financials(
    symbol: str,
    filing_type: FilingType = "consolidated",
    field: str | None = Query(default=None, description="A specific financial_facts field name, "
                                                          "e.g. 'revenue'. Omit for the default set."),
    history: bool = Query(default=False, description="Full period-by-period history instead of "
                                                       "just the latest value."),
    db_path: str = Depends(get_db_path),
):
    company = resolve_company(symbol, db_path)
    symbol = company["symbol"]

    if field:
        fields = [field]
    else:
        fields = _DEFAULT_FACT_FIELDS

    result: dict = {}
    for f in fields:
        if history:
            result[f] = fact_history(db_path, symbol, filing_type, f, dedupe=True)
        else:
            point = latest_fact(db_path, symbol, filing_type, f)
            result[f] = point

    return {
        "symbol": symbol,
        "filing_type": filing_type,
        "history": history,
        "facts": result,
        "warning": "Raw financial_facts values are reported exactly as extracted from the XBRL "
                   "filing -- unit/scale is not separately tracked (unlike /ratios, which carries "
                   "a unit column). Verify scale against the source filing before using downstream.",
    }