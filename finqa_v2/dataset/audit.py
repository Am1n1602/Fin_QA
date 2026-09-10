"""Coverage audit for finqa_v2.db (§15/§42) -- the "is this dataset production-quality?"
gate. Per company: facts / annual-period depth / statement mix / bank flag / segments /
documents / prices / valuation-readiness. Aggregates the gaps and a 0-100 score.

    python -m finqa_v2.dataset.audit [--v2-db PATH] [--index "NIFTY 50"]
        [--json OUT.json] [--check]        # --check exits 1 if any critical gap remains
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from finqa_v2.engine import FinancialEngine
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_FY = re.compile(r"FY\d{4}$")
_BANK_METRICS = ("bank_interest_earned", "bank_interest_expended", "advances", "deposits_debt")
_SINGLE_SEGMENT_OK = set()          # companies legitimately single-segment can be listed here


def _periods_any_basis(engine, ticker) -> tuple[list[str], str]:
    """Consolidated periods, falling back to standalone (SBILIFE files standalone only)."""
    for basis in ("consolidated", "standalone"):
        try:
            p = engine.periods(ticker, basis=basis)
        except Exception:
            p = []
        if p:
            return p, basis
    return [], "consolidated"


def _company_row(repos, engine, c) -> dict:
    metrics = set(repos.facts.metrics_for(c.company_id))
    is_bank = any(m in metrics for m in _BANK_METRICS)
    periods, basis = _periods_any_basis(engine, c.ticker)
    annual = [p for p in periods if _FY.match(p)]
    quarters = [p for p in periods if "Q" in p]
    segs = repos.segments.segments_for(c.company_id)
    docs = repos.documents.for_company(c.company_id)
    price = repos.prices.latest(c.company_id)

    val_metrics = ("pe", "pb") if not is_bank else ("pe", "pb", "ev_ebitda")
    val_ok = any(engine.get_ratio(c.ticker, v, basis=basis, period="latest_annual").value is not None
                 for v in val_metrics)

    return {
        "ticker": c.ticker, "name": c.name, "sector": c.sector, "active": c.active,
        "is_bank": is_bank, "basis": basis,
        "n_metrics": len(metrics), "n_annual": len(annual), "n_quarters": len(quarters),
        "annual_periods": annual,
        "has_pnl": any(m in metrics for m in ("revenue", "net_profit", "bank_interest_earned")),
        "has_balance_sheet": any(m in metrics for m in ("total_assets", "total_equity")),
        "has_cash_flow": "operating_cash_flow" in metrics,
        "n_segments": len(segs), "n_documents": len(docs),
        "has_prices": price is not None,
        "price_latest": price.price_date.isoformat() if price else None,
        "valuation_ready": val_ok,
    }


def audit_coverage(repos, *, index_name: str = "NIFTY 50") -> dict:
    engine = FinancialEngine(repos)
    idx = repos.indices.get_by_name(index_name)
    members = {c.ticker for c in repos.indices.members(idx.index_id)} if idx else set()
    companies = repos.companies.list()

    rows = [_company_row(repos, engine, c) for c in companies]
    by_ticker = {r["ticker"]: r for r in rows}

    def _pick(pred):
        return sorted(r["ticker"] for r in rows if pred(r))

    gaps = {
        "no_facts": _pick(lambda r: r["n_metrics"] == 0),
        "facts_but_no_annual": _pick(lambda r: r["n_metrics"] and r["n_annual"] == 0),
        "under_2_annual": _pick(lambda r: 0 < r["n_annual"] < 2),
        "missing_balance_sheet": _pick(lambda r: r["n_metrics"] and not r["has_balance_sheet"]),
        # informational only -- many companies legitimately report a single segment
        "no_segments_non_bank": _pick(
            lambda r: r["n_metrics"] and not r["is_bank"] and r["n_segments"] == 0
            and r["ticker"] not in _SINGLE_SEGMENT_OK),
        "no_documents": _pick(lambda r: r["n_documents"] == 0),
        "no_prices": _pick(lambda r: not r["has_prices"]),
        "valuation_unavailable": _pick(lambda r: r["n_metrics"] and not r["valuation_ready"]),
    }
    index_members_without_facts = sorted(
        t for t in members if by_ticker.get(t, {}).get("n_metrics", 0) == 0)

    # score: fraction of index members that are "complete" -- facts + a balance sheet +
    # >=2 annual periods + at least one document + prices. Segments are a bonus, not a gate.
    def _complete(r):
        return bool(r["n_metrics"] and r["has_balance_sheet"] and r["n_annual"] >= 2
                    and r["n_documents"] and r["has_prices"])

    member_rows = [by_ticker[t] for t in members if t in by_ticker]
    score = round(100 * sum(_complete(r) for r in member_rows) / max(1, len(member_rows)), 1)

    critical = bool(gaps["no_facts"] or index_members_without_facts
                    or gaps["missing_balance_sheet"] or gaps["facts_but_no_annual"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "index": index_name,
        "n_companies": len(companies),
        "n_index_members": len(members),
        "completeness_score": score,
        "critical": critical,
        "gaps": gaps,
        "index_members_without_facts": index_members_without_facts,
        "companies": rows,
    }


def _print(report: dict) -> None:
    print(f"\nfinqa_v2.db coverage -- {report['index']}  "
          f"({report['n_index_members']} members, {report['n_companies']} companies)")
    print(f"completeness score: {report['completeness_score']} / 100"
          + ("   [CRITICAL GAPS]" if report["critical"] else ""))
    print(f"{'ticker':<12}{'ann':>4}{'qtr':>4}{'seg':>4}{'doc':>4} {'px':>3} {'val':>4}  bank  sector")
    for r in sorted(report["companies"], key=lambda x: x["ticker"]):
        print(f"{r['ticker']:<12}{r['n_annual']:>4}{r['n_quarters']:>4}{r['n_segments']:>4}"
              f"{r['n_documents']:>4} {'Y' if r['has_prices'] else '.':>3} "
              f"{'Y' if r['valuation_ready'] else '.':>4}  {'B' if r['is_bank'] else ' '}    "
              f"{r['sector'] or ''}")
    print("\ngaps:")
    for k, v in report["gaps"].items():
        print(f"  {k:<26} {len(v):>3}  {', '.join(v[:12])}{' …' if len(v) > 12 else ''}")
    if report["index_members_without_facts"]:
        print(f"  {'index members, no facts':<26} {len(report['index_members_without_facts']):>3}  "
              f"{', '.join(report['index_members_without_facts'])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--index", default="NIFTY 50")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    with SqliteRepositories(args.v2_db) as repos:
        report = audit_coverage(repos, index_name=args.index)
    _print(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if (args.check and report["critical"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
