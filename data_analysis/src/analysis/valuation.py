import json
import sys
from pathlib import Path

import pandas as pd

from src.analysis.ratios import _is_single_quarter, _safe_div, compute_ebit, compute_net_debt, compute_total_debt
from src.analysis.combine_and_analyze import find_canonical_files
from src.config import EXTRACTION_PROJECT_DIR, ANALYSIS_OUTPUT_DIR

_DURATION_RANK = {"Six": 6, "Five": 5, "Four": 4, "Three": 3, "Two": 2, "One": 1}


def _duration_rank(record: dict) -> int:
    ctx = record.get("context_id", "")
    for prefix, rank in _DURATION_RANK.items():
        if ctx.startswith(prefix):
            return rank
    return 0


def _pick_latest_reliable_record(records: list[dict], required_field: str) -> tuple[dict | None, str | None]:
    """Among records where `required_field` is present, pick the most
    recent by period_end. Returns (chosen_record, warning).
    """
    candidates = [r for r in records if r.get(required_field) is not None]
    if not candidates:
        return None, None

    latest_period_end = max((r.get("period_end") or r.get("instant") or "") for r in candidates)
    tied = [r for r in candidates if (r.get("period_end") or r.get("instant") or "") == latest_period_end]

    if len(tied) == 1:
        return tied[0], None

    values = {r.get("context_id"): r[required_field] for r in tied}
    warning = None
    if len(set(values.values())) > 1:
        warning = (
            f"Multiple records share period_end={latest_period_end} but disagree on "
            f"{required_field}: {values}. Preferring the longest-duration context "
            f"(e.g. FourD over OneD) since standalone quarterly figures are typically "
            f"a management-computed plug, not independently re-verified — but this "
            f"disagreement likely indicates a real error in the source filing, not "
            f"just a rounding difference. Worth checking the raw filing directly."
        )

    tied.sort(key=_duration_rank, reverse=True)
    return tied[0], warning


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


def _sum_last_4_quarters(company: str, filing_type: str, value_fn) -> tuple[float, int] | tuple[None, int]:
    """Generic TTM-summing helper: sums value_fn(record) across the last
    4 single-quarter periods found across ALL canonical files for this
    company/filing_type. Returns (total, quarters_used) —
    quarters_used < 4 means the figure is partial.

    This is the one shared implementation behind compute_ttm_eps(),
    compute_ttm_ebit(), and compute_ttm_revenue() below — previously
    each was its own near-identical copy of this same find-filter-sort-
    sum sequence; consolidated here once a third copy would have made
    it four.
    """
    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))

    quarterly = [r for r in all_records if _is_single_quarter(r) and value_fn(r) is not None]
    quarterly.sort(key=lambda r: r.get("period_end") or "", reverse=True)
    last_4 = quarterly[:4]

    if not last_4:
        return None, 0
    return sum(value_fn(r) for r in last_4), len(last_4)


def compute_ttm_eps(company: str, filing_type: str, eps_field: str = "eps_basic") -> tuple[float, int] | tuple[None, int]:
    """Sums eps_basic across the last 4 single-quarter periods found across
    ALL canonical files for this company/filing_type. Returns
    (ttm_eps, quarters_used) — quarters_used < 4 means the TTM figure is
    partial (fewer than 4 real quarters available yet)."""
    return _sum_last_4_quarters(company, filing_type, lambda r: r.get(eps_field))


def compute_ttm_ebit(company: str, filing_type: str = "consolidated") -> tuple[float, int] | tuple[None, int]:
    """Sums compute_ebit() across the last 4 single-quarter periods —
    so Earnings Yield uses a trailing-twelve-month EBIT the same way
    P/E uses trailing EPS, rather than mixing a TTM numerator with a
    single-quarter one."""
    return _sum_last_4_quarters(company, filing_type, compute_ebit)


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
        
    with_equity = [r for r in all_records if r.get("total_equity") is not None and r.get("paid_up_equity_capital") is not None]
    latest, warning = _pick_latest_reliable_record(with_equity, "paid_up_equity_capital")

    result = {
        "company": company, "filing_type": filing_type,
        "latest_close": price, "price_date": price_date,
        "total_equity": None, "shares_outstanding": None,
        "book_value_per_share": None, "pb_ratio": None,
        "balance_sheet_as_of": None, "note": None,
        "data_quality_warning": warning,
    }

    if latest is None:
        result["note"] = "No record with total_equity found — need an annual/half-yearly filing extracted first."
        return result
    if price is None:
        result["note"] = "No price data found."
        return result

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


def compute_dividend_yield(company: str, filing_type: str = "consolidated") -> dict:
    """Dividend Yield = Dividend Per Share / Latest Price, where DPS is
    derived (total cash dividends paid / shares outstanding) rather than
    directly tagged — Ind AS reports dividends as a single cumulative
    financing-activity cash amount, not a per-share declared figure.

    Same single-latest-snapshot pattern as compute_pb() above, NOT
    TTM-summed like compute_ttm_eps()/compute_ttm_ebit() — 'dividends'
    only populates on annual (FourD-context) records to begin with,
    since Ind AS cash flow statements are cumulative-from-FY-start, so
    the latest annual record's dividends figure already IS the full
    year's total, the same way total_equity's latest snapshot already is
    the point-in-time balance.

    Caveat carried from ratios.py's payout_ratio_pct: 'dividends' is
    cash PAID during the fiscal year, which typically includes the
    PRIOR year's final dividend alongside the current year's interim —
    a standard cash-vs-declaration-basis timing mismatch, not an error.
    """
    price, price_date = get_latest_close_price(company)

    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))

    with_dividends = [r for r in all_records if r.get("dividends") is not None and r.get("paid_up_equity_capital") is not None]
    latest, warning = _pick_latest_reliable_record(with_dividends, "paid_up_equity_capital")

    result = {
        "company": company, "filing_type": filing_type,
        "latest_close": price, "price_date": price_date,
        "period": None, "total_dividends_paid": None,
        "shares_outstanding": None, "dividend_per_share": None,
        "dividend_yield_pct": None, "note": None,
        "data_quality_warning": warning,
    }

    if latest is None:
        result["note"] = "No record with dividends data found — needs an annual filing with the cash flow statement extracted."
        return result
    if price is None:
        result["note"] = "No price data found."
        return result

    shares = _safe_div(latest.get("paid_up_equity_capital"), latest.get("face_value_per_share"), as_pct=False)
    result["period"] = latest.get("period_end")
    result["total_dividends_paid"] = latest["dividends"]
    result["shares_outstanding"] = shares

    if not shares:
        result["note"] = "Could not derive shares outstanding (missing paid_up_equity_capital/face_value_per_share on this record)."
        return result

    dividend_per_share = latest["dividends"] / shares
    result["dividend_per_share"] = dividend_per_share
    result["dividend_yield_pct"] = (dividend_per_share / price) * 100 if price else None
    return result


def compute_enterprise_value(company: str, filing_type: str = "consolidated") -> dict:
    """EV = Market Cap + Total Debt - Cash, using the same
    most-recent-balance-sheet-record lookup compute_pb() already uses
    (debt and cash are balance-sheet-only fields, same annual/half-yearly
    availability constraint as total_equity).

    Borrowings absent on a record is treated as 0, matching
    ratios.py's existing debt_to_equity convention (debt-free IT
    companies genuinely have no borrowings tag at all). Cash absent is
    NOT defaulted to 0 — unlike "no debt", "no cash reported" almost
    certainly means missing data, not an actual zero cash balance, and
    defaulting it would silently understate Enterprise Value.
    """
    price, price_date = get_latest_close_price(company)

    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))

    with_equity = [r for r in all_records if r.get("total_equity") is not None and r.get("paid_up_equity_capital") is not None]
    latest, warning = _pick_latest_reliable_record(with_equity, "paid_up_equity_capital")

    result = {
        "company": company, "filing_type": filing_type,
        "latest_close": price, "price_date": price_date,
        "balance_sheet_as_of": None,
        "shares_outstanding": None, "market_cap": None,
        "total_debt": None, "cash_and_equivalents": None,
        "enterprise_value": None, "note": None,
        "data_quality_warning": warning,
    }

    if latest is None:
        result["note"] = "No record with balance-sheet data found — need an annual/half-yearly filing extracted first."
        return result
    if price is None:
        result["note"] = "No price data found."
        return result

    shares = _safe_div(latest.get("paid_up_equity_capital"), latest.get("face_value_per_share"), as_pct=False)
    result["balance_sheet_as_of"] = latest.get("period_end") or latest.get("instant")
    result["shares_outstanding"] = shares

    if not shares:
        result["note"] = "Could not derive shares outstanding (missing paid_up_equity_capital/face_value_per_share on this record)."
        return result

    if latest.get("cash_and_equivalents") is None:
        result["note"] = "cash_and_equivalents missing on this record — Enterprise Value not computed (defaulting it to 0 would silently overstate EV)."
        return result

    market_cap = price * shares
    net_debt = compute_net_debt(latest)  # shared with ratios.py — see its docstring
    total_debt = compute_total_debt(latest)  # shared, not re-derived
    cash = latest["cash_and_equivalents"]

    result["market_cap"] = market_cap
    result["total_debt"] = total_debt
    result["cash_and_equivalents"] = cash
    result["enterprise_value"] = market_cap + net_debt
    return result


def compute_earnings_yield(company: str, filing_type: str = "consolidated") -> dict:
    """Earnings Yield = TTM EBIT / Enterprise Value — Greenblatt's Magic
    Formula valuation metric. Uses the Capital-Employed-style EBIT
    already shared with roce_pct (see ratios.compute_ebit) rather than
    Greenblatt's literal formula, which needs Net Fixed Assets excluding
    goodwill — a field this pipeline doesn't have tagged and won't
    approximate. Both operands here are exact: EBIT is a real accounting
    identity, Enterprise Value is a real point-in-time balance-sheet +
    market-price computation.
    """
    ev_result = compute_enterprise_value(company, filing_type)
    ttm_ebit, n_quarters = compute_ttm_ebit(company, filing_type)

    result = {
        "company": company, "filing_type": filing_type,
        "enterprise_value": ev_result["enterprise_value"],
        "ttm_ebit": ttm_ebit,
        "quarters_used_for_ttm_ebit": n_quarters,
        "earnings_yield_pct": None,
        "note": None,
        "data_quality_warning": ev_result.get("data_quality_warning"),
    }

    if n_quarters < 4:
        result["note"] = f"Only {n_quarters}/4 quarters available — TTM EBIT is partial, Earnings Yield not computed."
        return result
    if ev_result["enterprise_value"] is None:
        result["note"] = f"Enterprise Value not available — {ev_result['note']}"
        return result
    if ev_result["enterprise_value"] <= 0:
        result["note"] = "Enterprise Value is zero/negative (net cash exceeds market cap) — Earnings Yield not meaningful as a standard ratio."
        return result

    result["earnings_yield_pct"] = (ttm_ebit / ev_result["enterprise_value"]) * 100
    return result


def compute_ttm_revenue(company: str, filing_type: str = "consolidated") -> tuple[float, int] | tuple[None, int]:
    """Sums revenue across the last 4 single-quarter periods, feeding
    compute_ev_to_sales() below."""
    return _sum_last_4_quarters(company, filing_type, lambda r: r.get("revenue"))


def compute_ev_to_sales(company: str, filing_type: str = "consolidated") -> dict:
    """EV/Sales = Enterprise Value / TTM Revenue. Unlike P/E and Earnings
    Yield, this stays meaningful for companies with negative or
    near-zero earnings — worth having once ranking scales past IT
    services into sectors/companies where that's a real possibility.
    """
    ev_result = compute_enterprise_value(company, filing_type)
    ttm_revenue, n_quarters = compute_ttm_revenue(company, filing_type)

    result = {
        "company": company, "filing_type": filing_type,
        "enterprise_value": ev_result["enterprise_value"],
        "ttm_revenue": ttm_revenue,
        "quarters_used_for_ttm_revenue": n_quarters,
        "ev_to_sales": None,
        "note": None,
        "data_quality_warning": ev_result.get("data_quality_warning"),
    }

    if n_quarters < 4:
        result["note"] = f"Only {n_quarters}/4 quarters available — TTM Revenue is partial, EV/Sales not computed."
        return result
    if ev_result["enterprise_value"] is None:
        result["note"] = f"Enterprise Value not available — {ev_result['note']}"
        return result
    if not ttm_revenue:
        result["note"] = "TTM Revenue is zero — EV/Sales not meaningful."
        return result

    result["ev_to_sales"] = ev_result["enterprise_value"] / ttm_revenue
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
    if pb_result.get("data_quality_warning"):
        print(f"  ⚠ DATA QUALITY WARNING: {pb_result['data_quality_warning']}")
    if pb_result["pb_ratio"] is not None:
        print(f"Book value/share:     {pb_result['book_value_per_share']:.2f} (as of {pb_result['balance_sheet_as_of']})")
        print(f"P/B ratio:            {pb_result['pb_ratio']:.2f}x")
    else:
        print(f"P/B ratio:            N/A — {pb_result['note']}")

    ey_result = compute_earnings_yield(company, filing_type)
    ey_out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_earnings_yield.json"
    ey_out_path.write_text(json.dumps(ey_result, indent=2, default=str))
    print()
    if ey_result.get("data_quality_warning"):
        print(f"  ⚠ DATA QUALITY WARNING: {ey_result['data_quality_warning']}")
    if ey_result["earnings_yield_pct"] is not None:
        print(f"Enterprise Value:     {ey_result['enterprise_value']:,.0f}")
        print(f"TTM EBIT:             {ey_result['ttm_ebit']:,.0f} ({ey_result['quarters_used_for_ttm_ebit']}/4 quarters)")
        print(f"Earnings Yield:       {ey_result['earnings_yield_pct']:.2f}%")
    else:
        print(f"Earnings Yield:       N/A — {ey_result['note']}")

    evs_result = compute_ev_to_sales(company, filing_type)
    evs_out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_ev_to_sales.json"
    evs_out_path.write_text(json.dumps(evs_result, indent=2, default=str))
    print()
    if evs_result["ev_to_sales"] is not None:
        print(f"TTM Revenue:          {evs_result['ttm_revenue']:,.0f} ({evs_result['quarters_used_for_ttm_revenue']}/4 quarters)")
        print(f"EV/Sales:             {evs_result['ev_to_sales']:.2f}x")
    else:
        print(f"EV/Sales:             N/A — {evs_result['note']}")

    dy_result = compute_dividend_yield(company, filing_type)
    dy_out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_dividend_yield.json"
    dy_out_path.write_text(json.dumps(dy_result, indent=2, default=str))
    print()
    if dy_result.get("data_quality_warning"):
        print(f"  ⚠ DATA QUALITY WARNING: {dy_result['data_quality_warning']}")
    if dy_result["dividend_yield_pct"] is not None:
        print(f"Total dividends paid: {dy_result['total_dividends_paid']:,.0f} (as of {dy_result['period']})")
        print(f"Dividend/share:       {dy_result['dividend_per_share']:.2f}")
        print(f"Dividend Yield:       {dy_result['dividend_yield_pct']:.2f}%")
    else:
        print(f"Dividend Yield:       N/A — {dy_result['note']}")

    print(f"\nSaved to {out_path}, {pb_out_path}, {ey_out_path}, {evs_out_path}, and {dy_out_path}")