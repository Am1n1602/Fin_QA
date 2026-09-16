"""GET /companies, GET /companies/{symbol}"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.database_ro import latest_metric, list_companies

from archive.api.deps import get_db_path, require_api_key, resolve_company
from archive.api.models import FilingType

router = APIRouter(prefix="/companies", tags=["companies"], dependencies=[Depends(require_api_key)])


_SNAPSHOT_METRICS = ["pe_ratio", "pb_ratio", "roe_pct", "npm_pct", "debt_to_equity", "latest_close"]


@router.get("")
def get_companies(db_path: str = Depends(get_db_path)) -> list[dict]:
    """All companies currently loaded in the database."""
    return list_companies(db_path)


@router.get("/{symbol}")
def get_company(symbol: str, filing_type: FilingType = "consolidated", db_path: str = Depends(get_db_path)) -> dict:
    """Company identity plus a small headline snapshot of the latest
    available value for a handful of commonly-asked metrics. Any metric
    with no data yet is returned as null, per the roadmap's "never silently
    convert missing data to zero" rule (Project Roadmap, Section 32) --
    this endpoint just extends that rule to "never omit the key either"."""
    company = resolve_company(symbol, db_path)
    snapshot = {}
    for metric_name in _SNAPSHOT_METRICS:
        point = latest_metric(db_path, company["symbol"], filing_type, metric_name)
        snapshot[metric_name] = {"period": point["period"], "value": point["value"]} if point else None
    return {**company, "filing_type": filing_type, "snapshot": snapshot}