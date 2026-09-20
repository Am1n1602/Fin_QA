"""Ratio reconciliation (roadmap Phase 3 / §13): compares a company-disclosed
XBRL ratio against the financial engine's own computation for the exact same
company/basis/period, and classifies the outcome. Per §6.3, the two are never
silently merged -- both values and both formulas are preserved side by side.

Reported ratios (finqa_v2/normalize/metrics.py's `*_reported` metrics, sourced
from SEBI LODR Reg 52(4) XBRL disclosures -- see TAG_MAP in
archive/data_extraction/src/extract/schema.py) are compared against their
nearest computed-ratio counterpart in finqa_v2/engine/ratios.py where one
exists. A company that never discloses a given reported ratio at all (most
don't -- Reg 52(4) applies only to issuers of listed non-convertible debt) is
not a data gap and is skipped entirely rather than flooding the output with
"missing_reported_ratio" rows that mean nothing.

    python -m finqa_v2.ratios.reconcile [--v2-db PATH] [--company TICKER1,TICKER2]
        [--json OUT.json] [--check]        # --check exits 1 if any formula_difference exists
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from finqa_v2.engine import ratios as _ratios
from finqa_v2.engine.records import build_period_records
from finqa_v2.models import Basis
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

# reported metric -> its nearest computed-ratio counterpart, or None when the
# engine has no formula for it at all (e.g. DSCR needs a principal-repayment
# breakdown the data model doesn't carry) -- that surfaces as "cannot_compute"
# rather than being silently skipped.
REPORTED_TO_COMPUTED: dict[str, str | None] = {
    "debt_equity_ratio_reported": "debt_to_equity",
    "interest_service_coverage_ratio_reported": "interest_coverage",
    "debt_service_coverage_ratio_reported": None,
}

_MATCH_TOL = 0.05          # <=5% relative difference
_SMALL_DIFF_TOL = 0.25     # <=25% relative difference


def _relative_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def _classify(reported: float | None, computed: float | None) -> str:
    if reported is None:
        return "missing_reported_ratio"
    if computed is None:
        return "cannot_compute"
    d = _relative_diff(reported, computed)
    if d <= _MATCH_TOL:
        return "matched"
    if d <= _SMALL_DIFF_TOL:
        return "small_difference"
    return "formula_difference"


def find_ratio_comparisons(repos, company: str | list[str] | None = None) -> list[dict]:
    """One entry per (company, basis, period, ratio) where a reported value, a
    computed value, or both exist. Never fabricates a comparison for a company
    that has no reported value for that ratio anywhere in its history."""
    tickers = _resolve_tickers(repos, company)
    out: list[dict] = []
    for ticker in tickers:
        comp = repos.companies.resolve(ticker)
        if comp is None:
            continue
        for basis in (Basis.CONSOLIDATED, Basis.STANDALONE):
            out.extend(_compare_company_basis(comp.ticker, repos, comp.company_id, basis))
    out.sort(key=lambda r: (r["company"], r["ratio"], r["basis"], r["financial_year"] or 0, r["quarter"] or 0))
    return out


def _resolve_tickers(repos, company) -> list[str]:
    if company is None:
        return [c.ticker for c in repos.companies.list()]
    if isinstance(company, str):
        return [company]
    return list(company)


def _compare_company_basis(ticker: str, repos, company_id: int, basis: Basis) -> list[dict]:
    records = build_period_records(repos, company_id, basis)
    out: list[dict] = []
    for reported_metric, computed_name in REPORTED_TO_COMPUTED.items():
        if not any(r.get(reported_metric) is not None for r in records):
            continue  # this company never discloses this ratio -- not a gap, just not applicable
        spec = _ratios.get_spec(computed_name) if computed_name else None
        for rec in records:
            reported_value = rec.get(reported_metric)
            computed_value = spec.compute(rec.values) if spec else None
            if reported_value is None and computed_value is None:
                continue
            status = _classify(reported_value, computed_value)
            diff = (
                round(reported_value - computed_value, 6)
                if reported_value is not None and computed_value is not None else None
            )
            out.append({
                "company": ticker,
                "basis": basis.value,
                "ratio": reported_metric.removesuffix("_reported"),
                "period": rec.label,
                "financial_year": rec.financial_year,
                "quarter": rec.quarter,
                "reported_value": reported_value,
                "computed_value": computed_value,
                "computed_formula": spec.formula if spec else None,
                "difference": diff,
                "status": status,
            })
    return out


def _print(rows: list[dict]) -> None:
    if not rows:
        print("ratio reconciliation: no reported ratios found in scope")
        return
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"ratio reconciliation: {len(rows)} comparison(s) -- " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for r in rows:
        if r["status"] in ("matched",):
            continue
        print(f"  {r['company']} {r['basis']} {r['ratio']} [{r['period']}] "
              f"reported={r['reported_value']!r} computed={r['computed_value']!r} "
              f"-> {r['status']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--company", default=None,
                    help="one ticker, or a comma-separated list (e.g. TCS,RELIANCE,INFY)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    company = [c.strip() for c in args.company.split(",") if c.strip()] if args.company else None

    with SqliteRepositories(args.v2_db) as repos:
        rows = find_ratio_comparisons(repos, company=company)

    _print(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if (args.check and any(r["status"] == "formula_difference" for r in rows)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
