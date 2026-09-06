"""GET /rankings -- fundamental ranking across a set of companies (or the
whole universe, or one sector), delegating to data_analysis's
compute_rankings() via AnalysisBridge (see qa_router/src/qa.py's
_handle_ranking()).

GET /companies/{symbol}/ranking -- the same thing scoped to one company's
own sector peers by default (falls back to the whole universe if that
company's sector isn't known yet)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.database_ro import list_companies

from api.deps import default_peer_group, get_analysis_bridge, get_db_path, parse_symbol_list, require_api_key, \
    resolve_company
from api.models import FilingType

router = APIRouter(tags=["rankings"], dependencies=[Depends(require_api_key)])


def _run_ranking(analysis_bridge, symbol_list: list[str], filing_type: str) -> dict:
    result = analysis_bridge.compute_rankings(symbol_list, filing_type)
    ordered = sorted(
        (s for s in symbol_list if result.get(s, {}).get("rank") is not None),
        key=lambda s: result[s]["rank"],
    )
    return {"symbols": symbol_list, "filing_type": filing_type, "ranking": result, "ordered_symbols": ordered,
            "note": "composite = equal-weighted percentile average across categories, "
                    "see data_analysis/src/analysis/ranking.py for the exact weights."}


@router.get("/rankings")
def get_rankings(
    symbols: str | None = Query(default=None, description="Comma-separated symbols, e.g. "
                                                            "'TCS,INFY,HCLTECH'. Takes precedence over "
                                                            "`sector` if both are given."),
    sector: str | None = Query(default=None, description="Rank only companies in this sector (exact "
                                                           "match against the companies table's `sector` "
                                                           "column, e.g. 'INFORMATION TECHNOLOGY')."),
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    symbol_list = parse_symbol_list(symbols)
    if not symbol_list and sector:
        symbol_list = [c["symbol"] for c in list_companies(db_path) if (c.get("sector") or "").upper() == sector.upper()]
    if not symbol_list:
        symbol_list = [c["symbol"] for c in list_companies(db_path)]
    return _run_ranking(analysis_bridge, symbol_list, filing_type)


@router.get("/companies/{symbol}/ranking")
def get_company_ranking(
    symbol: str,
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    company = resolve_company(symbol, db_path)
    symbol = company["symbol"]
    peers, sector_used = default_peer_group(db_path, symbol)
    result = _run_ranking(analysis_bridge, [symbol] + peers, filing_type)
    result["sector"] = company.get("sector")
    result["warning"] = (
        None if sector_used else
        "This company's sector isn't classified yet -- ranked against the entire database as a fallback."
    )
    return result