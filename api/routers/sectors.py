"""GET /sectors, GET /sectors/{sector}/comparison and the natural place to discover valid `sector=` values for
GET /rankings and to see how the sector grouping (src/universe.py's NSE-
sourced Industry data) actually came out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.database_ro import list_companies
from src.metrics import DEFAULT_COMPARISON_METRICS

from api.deps import get_analysis_bridge, get_db_path, parse_symbol_list, require_api_key
from api.models import FilingType

router = APIRouter(prefix="/sectors", tags=["sectors"], dependencies=[Depends(require_api_key)])

_UNCLASSIFIED = "UNCLASSIFIED"


@router.get("")
def list_sectors(db_path: str = Depends(get_db_path)) -> dict:
    """Every sector currently represented in the database, and which
    companies fall in each -- companies whose sector isn't resolved yet
    (src/universe.py hasn't captured Industry data for them, or the
    database hasn't been reloaded since it was added) are grouped under
    "UNCLASSIFIED" rather than silently dropped."""
    groups: dict[str, list[str]] = {}
    for c in list_companies(db_path):
        groups.setdefault(c.get("sector") or _UNCLASSIFIED, []).append(c["symbol"])
    return {"sectors": {k: sorted(v) for k, v in sorted(groups.items())}}


@router.get("/{sector}/comparison")
def sector_comparison(
    sector: str,
    metrics: str | None = Query(default=None, description="Comma-separated financial_metrics names. "
                                                            "Omit for the default comparison set."),
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    symbols = [c["symbol"] for c in list_companies(db_path) if (c.get("sector") or _UNCLASSIFIED).upper() == sector.upper()]
    metric_names = parse_symbol_list(metrics)
    metric_names = [m.lower() for m in metric_names] if metric_names else DEFAULT_COMPARISON_METRICS

    if not symbols:
        return {"sector": sector, "symbols": [], "metrics": metric_names, "filing_type": filing_type,
                "comparison": {}, "warning": f"No companies found with sector '{sector}' -- see GET "
                                             f"/sectors for the exact sector names currently in the database."}

    result = analysis_bridge.compare_peers(symbols, metric_names, filing_type)
    return {"sector": sector, "symbols": symbols, "metrics": metric_names, "filing_type": filing_type,
            "comparison": result}