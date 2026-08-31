import json
import sys
from pathlib import Path

import pandas as pd

from src.analysis.ratios import _is_single_quarter, _safe_div
from src.analysis.combine_and_analyze import find_canonical_files
from src.config import EXTRACTION_PROJECT_DIR, ANALYSIS_OUTPUT_DIR

def get_latest_close_price(symbol: str) -> tuple[float, str] | tuple[None, None]:
    """Reads {symbol}_prices.csv from data_extraction. Sorts explicitly by
    DATE rather than assuming row order, since jugaad-data's CSV order
    isn't a documented guarantee."""
    price_path = EXTRACTION_PROJECT_DIR / "data" / "prices" / f"{symbol}_prices.csv"
    if not price_path.exists():
        print(f"[valuation] No price file found at {price_path}")
        return None, None

    df = pd.read_csv(price_path, parse_dates=["DATE"])
    df = df.sort_values("DATE", ascending=False)
    latest = df.iloc[0]
    return float(latest["CLOSE"]), str(latest["DATE"].date())


def compute_ttm_eps(company: str, filing_type: str, eps_field: str = "eps_basic") -> tuple[float, int] | tuple[None, int]:
    """Sums eps_basic across the last 4 single-quarter periods found across
    ALL canonical files for this company/filing_type. Returns
    (ttm_eps, quarters_used) — quarters_used < 4 means the TTM figure is
    partial (fewer than 4 real quarters available yet)."""
    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))

    quarterly = [r for r in all_records if _is_single_quarter(r) and r.get(eps_field) is not None]
    quarterly.sort(key=lambda r: r.get("period_end") or "", reverse=True)
    last_4 = quarterly[:4]

    if not last_4:
        return None, 0
    return sum(r[eps_field] for r in last_4), len(last_4)


def compute_pe(company: str, filing_type: str = "consolidated", eps_field: str = "eps_basic") -> dict:
    price, price_date = get_latest_close_price(company)
    ttm_eps, n_quarters = compute_ttm_eps(company, filing_type, eps_field)

    result = {
        "company": company,
        "filing_type": filing_type,
        "eps_field": eps_field,
        "latest_close": price,
        "price_date": price_date,
        "ttm_eps": ttm_eps,
        "quarters_used_for_ttm": n_quarters,
        "pe_ratio": None,
        "note": None,
    }

    if n_quarters < 4:
        result["note"] = f"Only {n_quarters}/4 quarters available — TTM EPS is partial, P/E not computed."
        return result
    if price is None:
        result["note"] = "No price data found."
        return result
    if ttm_eps is None or ttm_eps <= 0:
        result["note"] = "TTM EPS is zero/negative — P/E not meaningful (company posted a net loss over the trailing year)."
        return result

    result["pe_ratio"] = price / ttm_eps
    return result


def compute_pb(company: str, filing_type: str = "consolidated") -> dict:
    """P/B = latest price / book value per share. Needs total_equity,
    which only exists on records merge_periods() successfully matched
    with a balance-sheet instant context — most likely just your
    annual/half-yearly filing(s), not every quarter."""
    price, price_date = get_latest_close_price(company)

    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))

    # Most recent record that actually has total_equity populated
    with_equity = [r for r in all_records if r.get("total_equity") is not None]
    with_equity.sort(key=lambda r: r.get("period_end") or r.get("instant") or "", reverse=True)

    result = {
        "company": company, "filing_type": filing_type,
        "latest_close": price, "price_date": price_date,
        "total_equity": None, "shares_outstanding": None,
        "book_value_per_share": None, "pb_ratio": None,
        "balance_sheet_as_of": None, "note": None,
    }

    if not with_equity:
        result["note"] = "No record with total_equity found — need an annual/half-yearly filing extracted first."
        return result
    if price is None:
        result["note"] = "No price data found."
        return result

    latest = with_equity[0]
    equity = latest["total_equity"]
    shares = _safe_div(latest.get("paid_up_equity_capital"), latest.get("face_value_per_share"), as_pct=False)
    result["balance_sheet_as_of"] = latest.get("period_end") or latest.get("instant")
    result["total_equity"] = equity
    result["shares_outstanding"] = shares

    if not shares:
        result["note"] = "Could not derive shares outstanding (missing paid_up_equity_capital/face_value_per_share on this record)."
        return result

    book_value_per_share = equity / shares
    result["book_value_per_share"] = book_value_per_share
    result["pb_ratio"] = price / book_value_per_share if book_value_per_share else None
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.analysis.valuation <company_symbol> [consolidated|standalone]")
        sys.exit(1)
    company = sys.argv[1]
    filing_type = sys.argv[2] if len(sys.argv) > 2 else "consolidated"

    result = compute_pe(company, filing_type)

    out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_valuation.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(f"Company:              {result['company']} ({result['filing_type']})")
    print(f"Latest close:         {result['latest_close']} (as of {result['price_date']})")
    print(f"TTM EPS ({result['eps_field']}):  {result['ttm_eps']} ({result['quarters_used_for_ttm']}/4 quarters)")
    if result["pe_ratio"] is not None:
        print(f"P/E ratio:            {result['pe_ratio']:.2f}x")
    else:
        print(f"P/E ratio:            N/A — {result['note']}")

    pb_result = compute_pb(company, filing_type)
    pb_out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_pb.json"
    pb_out_path.write_text(json.dumps(pb_result, indent=2, default=str))
    print()
    if pb_result["pb_ratio"] is not None:
        print(f"Book value/share:     {pb_result['book_value_per_share']:.2f} (as of {pb_result['balance_sheet_as_of']})")
        print(f"P/B ratio:            {pb_result['pb_ratio']:.2f}x")
    else:
        print(f"P/B ratio:            N/A — {pb_result['note']}")

    print(f"\nSaved to {out_path} and {pb_out_path}")
