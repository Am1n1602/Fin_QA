"""GET /companies/{symbol}/peers -- peer comparison, delegating to
data_analysis's compare_peers() via AnalysisBridge (see
qa_router/src/qa.py's _handle_comparison()).

Default peer group (no `peers=` passed) is now same-sector companies, not
the whole NIFTY 50 universe -- see api/deps.py's default_peer_group() and
qa_router/src/qa.py's _peer_universe() for the shared reasoning."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.metrics import DEFAULT_COMPARISON_METRICS

from archive.api.deps import default_peer_group, get_analysis_bridge, get_db_path, parse_symbol_list, require_api_key, \
    resolve_company
from archive.api.models import FilingType

router = APIRouter(prefix="/companies/{symbol}/peers", tags=["peers"], dependencies=[Depends(require_api_key)])


@router.get("")
def get_peer_comparison(
    symbol: str,
    peers: str | None = Query(default=None, description="Comma-separated peer symbols, e.g. "
                                                          "'INFY,HCLTECH'. Omit to compare against this "
                                                          "company's own sector peers by default (falls "
                                                          "back to the whole database if its sector isn't "
                                                          "known yet)."),
    metrics: str | None = Query(default=None, description="Comma-separated financial_metrics names. "
                                                            "Omit for the default comparison set."),
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    company = resolve_company(symbol, db_path)
    symbol = company["symbol"]

    peer_symbols = parse_symbol_list(peers)
    sector_used: str | None = None
    used_explicit_peers = bool(peer_symbols)
    if not peer_symbols:
        peer_symbols, sector_used = default_peer_group(db_path, symbol)

    metric_names = parse_symbol_list(metrics)  # comma-split works the same for metric names
    metric_names = [m.lower() for m in metric_names] if metric_names else DEFAULT_COMPARISON_METRICS

    all_symbols = [symbol] + [p for p in peer_symbols if p != symbol]
    result = analysis_bridge.compare_peers(all_symbols, metric_names, filing_type)

    warning = None
    if not used_explicit_peers:
        warning = (
            f"No peers were specified, so this compares against {sector_used} sector peers by default."
            if sector_used else
            "No peers were specified and this company's sector isn't classified yet (re-run the "
            "universe refresh + reload the database) -- comparing against the entire database as a "
            "fallback."
        )

    return {"symbol": symbol, "sector": company.get("sector"), "peers": peer_symbols, "metrics": metric_names,
            "filing_type": filing_type, "comparison": result, "warning": warning}