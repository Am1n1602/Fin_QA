"""
data_analysis/src/reports/aggregator.py

"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from src.analysis.ratios import analyze
from src.analysis.valuation import (
    compute_pe, compute_pb, compute_enterprise_value, compute_earnings_yield,
    compute_ev_to_sales, compute_dividend_yield,
)
from src.analysis.combine_and_analyze import find_canonical_files
from src.analysis.financial_health import compute_financial_health
from src.analysis.peer_comparison import compare_peers, _get_connection
from src.analysis.ranking import compute_rankings


CAVEATS = [
    "Growth figures are real single-year YoY, not multi-year CAGR — NSE's real filing-history "
    "ceiling (~15 months) blocks true CAGR regardless of requested window; BSE has deeper history "
    "but attachments are PDF-only (no XBRL).",
    "Piotroski F-Score is 8 of 9 criteria — Delta Gross Margin is excluded (no clean COGS-equivalent "
    "tag for Ind AS IT-services filings) and is NOT scored as failing.",
    "Altman Z-score is PARTIAL (X1/X3/X4 only) — X2 (Retained Earnings/Total Assets) is excluded, "
    "not approximated (no clean tag available). 'partial_z' is NOT the official Altman Z''-Score and "
    "its published 2.6/1.1 safe/distress thresholds do not apply to it.",
    "This entire analytical framework (Capital Employed, Enterprise Value, current-liabilities-based "
    "Safety) is built for operating companies. It does not apply to banks/NBFCs.",
]

PEER_COMPARISON_METRICS = [
    "npm_pct", "roe_pct", "operating_roce_pct", "roa_pct",
    "current_ratio", "debt_to_equity", "cash_ratio",
    "earnings_yield_pct", "pe_ratio", "pb_ratio", "ev_to_sales",
]


def _load_all_records(company: str, filing_type: str) -> list[dict]:
    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))
    return all_records


def _get_company_name(conn, symbol: str) -> str:
    """Looks up the company's display name directly from the companies
    table via the already-open connection, rather than importing
    database's config.py — that would hit the same src/src package-name
    collision peer_comparison.py's own docstring already documents.
    Falls back to the symbol itself if not found."""
    row = conn.execute("SELECT name FROM companies WHERE symbol=?", (symbol,)).fetchone()
    return row["name"] if row and row["name"] else symbol


def _piotroski_flag_detail(name: str, c: dict) -> str:
    """accruals has a different dict shape (cfo_pct/roa_pct) than every
    other Piotroski criterion (latest/prior) — see financial_health.py's
    print_financial_health() for the same special-case."""
    if name == "accruals":
        return f"{name}: cfo_pct={c.get('cfo_pct')} vs roa_pct={c.get('roa_pct')}"
    return f"{name}: latest={c.get('latest')} vs prior={c.get('prior')}"


def _build_flags(health: dict, ranking_result: Optional[dict], annual_yoy: Optional[dict]) -> list[dict]:

    flags = []

    piotroski = health.get("piotroski", {})
    for name, c in piotroski.get("criteria", {}).items():
        if c.get("met") is True:
            flags.append({"type": "strength", "source": "piotroski", "signal": name,
                          "detail": _piotroski_flag_detail(name, c)})
        elif c.get("met") is False:
            flags.append({"type": "risk", "source": "piotroski", "signal": name,
                          "detail": _piotroski_flag_detail(name, c)})

    for w in health.get("balance_sheet_strength", {}).get("warnings", []):
        flags.append({"type": "risk", "source": "balance_sheet_strength", "signal": "warning", "detail": w})

    if ranking_result:
        for cat, score in ranking_result.get("category_scores", {}).items():
            if score is None:
                continue
            if score >= 75:
                flags.append({"type": "strength", "source": "ranking", "signal": cat,
                              "detail": f"{cat} percentile score {score} — top quartile within peer group"})
            elif score <= 25:
                flags.append({"type": "risk", "source": "ranking", "signal": cat,
                              "detail": f"{cat} percentile score {score} — bottom quartile within peer group"})

    if annual_yoy:
        for field in ("revenue_growth_pct", "net_profit_growth_pct", "eps_basic_growth_pct"):
            val = annual_yoy.get(field)
            if val is None:
                continue
            flags.append({
                "type": "strength" if val > 0 else "risk",
                "source": "annual_yoy", "signal": field,
                "detail": f"{field}: {val:+.2f}% YoY ({annual_yoy.get('prior_period_end')} -> {annual_yoy.get('latest_period_end')})",
            })

    return flags


def compute_company_report(
    symbol: str,
    peer_symbols: list,
    filing_type: str = "consolidated",
    db_path: Optional[str] = None,
    conn=None,
) -> dict:
    owns_conn = False
    if conn is None:
        if db_path is None:
            raise ValueError("compute_company_report requires either db_path or conn")
        conn = _get_connection(db_path)
        owns_conn = True

    try:
        company_name = _get_company_name(conn, symbol)

        # --- File-based: ratios, QoQ trends, annual YoY growth (Stages 3-4) ---
        records = _load_all_records(symbol, filing_type)
        analysis = analyze(records)
        latest_period = analysis["periods"][0] if analysis["periods"] else None

        # --- File-based: valuation ---
        pe_result = compute_pe(symbol, filing_type)
        pb_result = compute_pb(symbol, filing_type)
        ev_result = compute_enterprise_value(symbol, filing_type)
        ey_result = compute_earnings_yield(symbol, filing_type)
        evs_result = compute_ev_to_sales(symbol, filing_type)
        dy_result = compute_dividend_yield(symbol, filing_type)

        # --- File-based: Financial Health (Stage 7) ---
        health = compute_financial_health(symbol, filing_type)

        # --- DB-based: Peer Comparison (Stage 5) + Ranking (Stage 6) ---
        all_symbols = [symbol] + [s for s in peer_symbols if s != symbol]
        peer_result = compare_peers(all_symbols, PEER_COMPARISON_METRICS, filing_type=filing_type, conn=conn)
        ranking_all = compute_rankings(all_symbols, filing_type=filing_type, conn=conn)
        ranking_result = ranking_all.get(symbol)

        flags = _build_flags(health, ranking_result, analysis.get("annual_yoy"))

        source_files = [f.name for f in find_canonical_files(symbol, filing_type)]

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "company": {"symbol": symbol, "name": company_name, "filing_type": filing_type},
            "peer_symbols": [s for s in peer_symbols if s != symbol],

            "company_overview": {
                "latest_close": pe_result.get("latest_close"),
                "price_date": pe_result.get("price_date"),
                "latest_period_end": latest_period.get("period_end") if latest_period else None,
            },
            "financial_performance": latest_period.get("ratios") if latest_period else None,
            "growth": analysis.get("annual_yoy"),
            "trends_qoq": analysis.get("trends"),
            "valuation": {
                "pe_ratio": pe_result.get("pe_ratio"),
                "pb_ratio": pb_result.get("pb_ratio"),
                "earnings_yield_pct": ey_result.get("earnings_yield_pct"),
                "ev_to_sales": evs_result.get("ev_to_sales"),
                "dividend_yield_pct": dy_result.get("dividend_yield_pct"),
                "enterprise_value": ev_result.get("enterprise_value"),
                "data_quality_warnings": [
                    w for w in (
                        pb_result.get("data_quality_warning"),
                        ev_result.get("data_quality_warning"),
                        dy_result.get("data_quality_warning"),
                    ) if w
                ],
            },
            "peer_comparison": peer_result,
            "ranking": ranking_result,
            "ranking_full_peer_set": ranking_all,
            "financial_health": health,

            "flags": flags,
            "data_sources": {"canonical_files": source_files},
            "caveats": CAVEATS,
        }
        return report
    finally:
        if owns_conn:
            conn.close()


def print_report_summary(report: dict) -> None:
    """Short human-readable summary — the full report is meant to be
    consumed as JSON (by Part B eventually), not read on a terminal, so
    this is deliberately brief rather than dumping every section."""
    c = report["company"]
    print(f"\n=== Report: {c['name']} ({c['symbol']}, {c['filing_type']}) ===")
    print(f"Generated: {report['generated_at']}")
    print(f"Peers: {report['peer_symbols']}")

    r = report.get("ranking")
    if r:
        print(f"\nRanking: composite={r.get('composite_score')} rank={r.get('rank')}")
        print(f"  Category scores: {r.get('category_scores')}")

    h = report["financial_health"]["piotroski"]
    print(f"\nPiotroski: {h.get('score')}/{h.get('max_possible_score')}")

    print(f"\nFlags ({len(report['flags'])} total):")
    for f in report["flags"]:
        marker = "+" if f["type"] == "strength" else "-"
        print(f"  [{marker}] ({f['source']}) {f['detail']}")

    if any(report["valuation"]["data_quality_warnings"]):
        print(f"\n⚠ Data quality warnings present — see report['valuation']['data_quality_warnings']")


def save_report(report: dict, symbol: str, filing_type: str, output_dir: str = "data/processed/reports") -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{symbol}_{filing_type}_report.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    return path


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("Usage: python -m src.reports.aggregator <db_path> <filing_type> <symbol> <peer1,peer2,...>")
        sys.exit(1)

    _db_path, _filing_type, _symbol, _peers_arg = sys.argv[1:5]
    _peer_symbols = [s.strip() for s in _peers_arg.split(",")]

    _report = compute_company_report(_symbol, _peer_symbols, filing_type=_filing_type, db_path=_db_path)
    print_report_summary(_report)

    _saved_path = save_report(_report, _symbol, _filing_type)
    print(f"\nSaved full report to {_saved_path}")