"""GET /companies/{symbol}/report -- combined report (ranking + peer
comparison + flags), delegating to data_analysis's compute_company_report()
via AnalysisBridge (see qa_router/src/qa.py's _handle_report()). This is the
deterministic, structured half of Stage 8's "Automated Research Reports" --
the LLM narrative layer sits on top of exactly this data via POST /qa, structured
analysis first, LLM narrative second, never the reverse."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.deps import default_peer_group, get_analysis_bridge, get_db_path, parse_symbol_list, require_api_key, \
    resolve_company
from api.models import FilingType

router = APIRouter(prefix="/companies/{symbol}/report", tags=["reports"], dependencies=[Depends(require_api_key)])


@router.get("")
def get_company_report(
    symbol: str,
    peers: str | None = Query(default=None, description="Comma-separated peer symbols. Omit to "
                                                          "benchmark against this company's own sector "
                                                          "peers by default (falls back to the whole "
                                                          "database if its sector isn't known yet)."),
    filing_type: FilingType = "consolidated",
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
) -> dict:
    company = resolve_company(symbol, db_path)
    symbol = company["symbol"]

    peer_symbols = parse_symbol_list(peers)
    used_explicit_peers = bool(peer_symbols)
    sector_used: str | None = None
    if not peer_symbols:
        peer_symbols, sector_used = default_peer_group(db_path, symbol)

    result = analysis_bridge.compute_company_report(symbol, peer_symbols, filing_type)
    if not used_explicit_peers:
        result["peer_selection_warning"] = (
            f"No peers were specified, so this benchmarks against {sector_used} sector peers by default."
            if sector_used else
            "No peers were specified and this company's sector isn't classified yet -- benchmarking "
            "against the entire database as a fallback."
        )
    return result