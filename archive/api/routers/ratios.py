"""GET /companies/{symbol}/ratios -- computed, verified metrics
(financial_metrics table)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.database_ro import latest_metric, metric_history
from src.metrics import METRICS

from archive.api.deps import get_db_path, require_api_key, resolve_company
from archive.api.models import FilingType

router = APIRouter(prefix="/companies/{symbol}/ratios", tags=["ratios"],
                    dependencies=[Depends(require_api_key)])

_DEFAULT_METRIC_FIELDS = [m.field for m in METRICS if m.table == "financial_metrics"]


@router.get("")
def get_ratios(
    symbol: str,
    filing_type: FilingType = "consolidated",
    metric: str | None = Query(default=None, description="A specific financial_metrics name, "
                                                           "e.g. 'roe_pct'. Omit for the default set."),
    history: bool = Query(default=False, description="Full period-by-period history instead of "
                                                       "just the latest value."),
    single_quarter_only: bool = Query(default=False, description="History only: restrict to real "
                                                                   "single-quarter periods, excluding "
                                                                   "YTD/cumulative and annual rows."),
    db_path: str = Depends(get_db_path),
):
    company = resolve_company(symbol, db_path)
    symbol = company["symbol"]

    metrics_to_fetch = [metric] if metric else _DEFAULT_METRIC_FIELDS

    result: dict = {}
    for m in metrics_to_fetch:
        if history:
            result[m] = metric_history(db_path, symbol, filing_type, m,
                                        single_quarter_only=single_quarter_only, dedupe=True)
        else:
            point = latest_metric(db_path, symbol, filing_type, m)
            result[m] = point

    return {"symbol": symbol, "filing_type": filing_type, "history": history, "ratios": result}