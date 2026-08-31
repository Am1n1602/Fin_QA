import json
import statistics
import sys

from src.analysis.ratios import _is_single_quarter, _is_annual, compute_period_ratios
from src.analysis.combine_and_analyze import find_canonical_files
from src.config import ANALYSIS_OUTPUT_DIR

# The 1 Piotroski criterion permanently excluded here, and why —
# referenced by compute_piotroski() so the reason lives in exactly one
# place. cfo_positive and accruals used to be here too, before
# operating_cash_flow was confirmed mapped this session.
PIOTROSKI_EXCLUDED = {
    "delta_gross_margin": "Ind AS IT-services filings have no clean COGS-equivalent tag to compute gross margin.",
}

def _load_all_records(company: str, filing_type: str) -> list[dict]:
    files = find_canonical_files(company, filing_type)
    all_records = []
    for f in files:
        all_records.extend(json.loads(f.read_text()))
    return all_records

def _latest_two_annual_periods(records: list[dict]) -> list[dict]:
    """The 2 most recent annual-duration (~365 day) records with a
    balance sheet present, sorted latest-first. Piotroski's 6 computable
    criteria all need real annual figures, not YTD-cumulative or
    quarterly ones sharing a period_end with them."""
    annual = [r for r in records if _is_annual(r) and r.get("total_assets") is not None]
    annual.sort(key=lambda r: r.get("period_end") or "", reverse=True)
    return annual[:2]

def compute_piotroski(company: str, filing_type: str = "consolidated") -> dict:
    """8-of-9 Piotroski F-Score. See module docstring for the 1 excluded
    criterion and why — it is NOT scored as failing."""
    records = _load_all_records(company, filing_type)
    periods = _latest_two_annual_periods(records)

    result = {
        "company": company, "filing_type": filing_type,
        "score": None, "max_possible_score": None,
        "criteria": {}, "excluded_criteria": PIOTROSKI_EXCLUDED,
        "latest_period": None, "prior_period": None,
        "note": None,
    }

    if len(periods) < 2:
        result["note"] = (
            f"Only {len(periods)} annual period(s) with balance-sheet data available "
            f"— need 2 for year-over-year comparison."
        )
        return result

    latest, prior = periods[0], periods[1]
    result["latest_period"] = latest.get("period_end")
    result["prior_period"] = prior.get("period_end")

    latest_r = compute_period_ratios(latest)
    prior_r = compute_period_ratios(prior)

    def _criterion(latest_val, prior_val, comparator):
        if latest_val is None or (comparator != "positive" and prior_val is None):
            return {"met": None, "latest": latest_val, "prior": prior_val, "reason": "insufficient_data"}
        if comparator == "positive":
            met = latest_val > 0
        elif comparator == "greater":
            met = latest_val > prior_val
        elif comparator == "less":
            met = latest_val < prior_val
        else:  # "less_or_equal"
            met = latest_val <= prior_val
        return {"met": met, "latest": latest_val, "prior": prior_val, "reason": None}

    criteria = {
        "roa_positive": _criterion(latest_r.get("roa_pct"), None, "positive"),
        "roa_improving": _criterion(latest_r.get("roa_pct"), prior_r.get("roa_pct"), "greater"),
        "cfo_positive": _criterion(latest_r.get("cfo_pct"), None, "positive"),
        "leverage_decreasing": _criterion(
            latest_r.get("longterm_leverage_pct"), prior_r.get("longterm_leverage_pct"), "less"
        ),
        "liquidity_improving": _criterion(
            latest_r.get("current_ratio"), prior_r.get("current_ratio"), "greater"
        ),
        "no_dilution": _criterion(
            latest_r.get("shares_outstanding"), prior_r.get("shares_outstanding"), "less_or_equal"
        ),
        "asset_turnover_improving": _criterion(
            latest_r.get("asset_turnover"), prior_r.get("asset_turnover"), "greater"
        ),
    }

    # Accruals: CFO/Assets > ROA, both from the SAME period — not a
    # year-over-year comparison like every other criterion above, so
    # built directly rather than through _criterion(), whose "latest vs
    # prior" field names would misleadingly suggest a YoY check here.
    cfo_pct, roa_pct = latest_r.get("cfo_pct"), latest_r.get("roa_pct")
    if cfo_pct is None or roa_pct is None:
        criteria["accruals"] = {"met": None, "cfo_pct": cfo_pct, "roa_pct": roa_pct, "reason": "insufficient_data"}
    else:
        criteria["accruals"] = {"met": cfo_pct > roa_pct, "cfo_pct": cfo_pct, "roa_pct": roa_pct, "reason": None}

    result["criteria"] = criteria

    computed = [c for c in criteria.values() if c["met"] is not None]
    result["score"] = sum(1 for c in computed if c["met"])
    result["max_possible_score"] = len(computed)
    if len(computed) < 8:
        result["note"] = f"Only {len(computed)}/8 intended criteria had enough data this run — see individual 'reason' fields."
    return result


def compute_altman_z_partial(company: str, filing_type: str = "consolidated") -> dict:
    """X1, X3, X4 of Altman's Z''-Score (emerging-market/non-manufacturer
    variant), using the latest available balance-sheet period. X2
    (Retained Earnings/Total Assets) is omitted, NOT approximated.

    IMPORTANT: the returned 'partial_z' is NOT the official Altman
    Z''-Score, and the published 2.6/1.1 safe/distress thresholds do NOT
    validly apply to it — see module docstring for why dropping a term
    from a fitted linear formula isn't a smaller, still-valid version of
    it. Use x1/x3/x4 individually as directional signals; treat
    partial_z as informational only, never as a classification.
    """
    records = _load_all_records(company, filing_type)
    annual = _latest_two_annual_periods(records)

    result = {
        "company": company, "filing_type": filing_type,
        "period": None,
        "x1_working_capital_to_assets": None,
        "x3_ebit_to_assets": None,
        "x4_equity_to_liabilities": None,
        "partial_z": None,
        "x2_omitted_reason": (
            "No Retained Earnings tag available — Reserves & Surplus (total_equity - "
            "paid_up_equity_capital) was deliberately not used as a substitute, since it "
            "includes securities premium/general reserve/other components beyond retained "
            "earnings specifically, and this project does not approximate inputs."
        ),
        "note": (
            "partial_z uses Altman's published X1/X3/X4 coefficients with X2's term dropped "
            "entirely — this is NOT equivalent to a valid reduced-form Z''-Score. The official "
            "2.6 (safe) / 1.1 (distress) thresholds do not apply here. Use x1/x3/x4 individually; "
            "treat partial_z as informational only, not a classification."
        ),
    }

    if not annual:
        result["note"] = "No annual period with balance-sheet data available."
        return result

    latest = annual[0]
    result["period"] = latest.get("period_end")
    r = compute_period_ratios(latest)

    x1 = r.get("working_capital_to_assets_pct")
    x3 = r.get("ebit_to_assets_pct")
    x4 = r.get("equity_to_liabilities_pct")

    result["x1_working_capital_to_assets"] = x1
    result["x3_ebit_to_assets"] = x3
    result["x4_equity_to_liabilities"] = x4

    if None not in (x1, x3, x4):
        # Altman's published coefficients operate on decimal ratios, not
        # percentages — divide by 100 before applying them.
        result["partial_z"] = round(3.25 + 6.56 * (x1 / 100) + 6.72 * (x3 / 100) + 1.05 * (x4 / 100), 3)

    return result


def compute_balance_sheet_strength(company: str, filing_type: str = "consolidated") -> dict:
    """Snapshot of the latest period's Safety-category ratios — same
    fields ranking.py's Safety category draws from, reused not
    recomputed. No peer group needed: this answers "how strong is this
    company's balance sheet", not "stronger than whom"."""
    records = _load_all_records(company, filing_type)
    annual = _latest_two_annual_periods(records)

    result = {
        "company": company, "filing_type": filing_type,
        "period": None, "metrics": {}, "warnings": [], "note": None,
    }

    if not annual:
        result["note"] = "No annual period with balance-sheet data available."
        return result

    latest = annual[0]
    result["period"] = latest.get("period_end")
    r = compute_period_ratios(latest)

    fields = [
        "working_capital_to_assets_pct", "equity_to_liabilities_pct", "debt_to_equity",
        "current_ratio", "cash_ratio", "interest_coverage_ratio", "net_debt_to_operating_ebit",
    ]
    result["metrics"] = {f: r.get(f) for f in fields}

    # One deliberately conservative, well-established flag — current
    # ratio below 1.0 is a textbook liquidity concern (current
    # liabilities exceed current assets). Not adding more numeric
    # thresholds here (e.g. "high" debt/equity) since acceptable
    # leverage varies too much by context to assert a universal cutoff
    # without misrepresenting confidence in a specific number.
    if result["metrics"]["current_ratio"] is not None and result["metrics"]["current_ratio"] < 1.0:
        result["warnings"].append("current_ratio below 1.0 — current liabilities exceed current assets")

    return result


def compute_earnings_consistency(company: str, filing_type: str = "consolidated") -> dict:
    """Coefficient of variation (stdev/mean) of npm_pct across available
    real quarters. Lower = more stable margins. A standard statistical
    dispersion measure, not a named academic model on its own — flagged
    if fewer than 3 quarters are available, since CV isn't meaningful on
    1-2 data points."""
    records = _load_all_records(company, filing_type)
    quarterly = [r for r in records if _is_single_quarter(r)]
    quarterly.sort(key=lambda r: r.get("period_end") or "")

    npm_series = []
    for r in quarterly:
        ratios = compute_period_ratios(r)
        if ratios.get("npm_pct") is not None:
            npm_series.append({"period_end": r.get("period_end"), "npm_pct": ratios["npm_pct"]})

    result = {
        "company": company, "filing_type": filing_type,
        "quarters_used": len(npm_series), "npm_series": npm_series,
        "mean_npm_pct": None, "coefficient_of_variation": None, "note": None,
    }

    if len(npm_series) < 3:
        result["note"] = (
            f"Only {len(npm_series)} quarter(s) with npm_pct available — "
            f"need >=3 for a meaningful coefficient of variation."
        )
        return result

    values = [p["npm_pct"] for p in npm_series]
    mean = statistics.mean(values)
    result["mean_npm_pct"] = round(mean, 4)
    if mean != 0:
        result["coefficient_of_variation"] = round(statistics.stdev(values) / abs(mean), 4)
    else:
        result["note"] = "Mean NPM is exactly 0 — coefficient of variation undefined."

    return result


def compute_financial_health(company: str, filing_type: str = "consolidated") -> dict:
    """Runs all 4 analyses and returns them together, still separate —
    see module docstring for why there's no combined health_score."""
    return {
        "company": company,
        "filing_type": filing_type,
        "piotroski": compute_piotroski(company, filing_type),
        "altman_z_partial": compute_altman_z_partial(company, filing_type),
        "balance_sheet_strength": compute_balance_sheet_strength(company, filing_type),
        "earnings_consistency": compute_earnings_consistency(company, filing_type),
    }


def print_financial_health(result: dict) -> None:
    print(f"\n=== Financial Health: {result['company']} ({result['filing_type']}) ===")

    p = result["piotroski"]
    print(f"\n--- Piotroski F-Score: {p['score']}/{p['max_possible_score']} "
          f"(of 8 intended; 1 permanently excluded — see below) ---")
    if p["note"]:
        print(f"  NOTE: {p['note']}")
    for name, c in p["criteria"].items():
        status = "MET" if c["met"] else ("NOT MET" if c["met"] is False else "N/A")
        if name == "accruals":
            print(f"  {name:28s} {status:8s} cfo_pct={c['cfo_pct']} roa_pct={c['roa_pct']}")
        else:
            print(f"  {name:28s} {status:8s} latest={c['latest']} prior={c['prior']}")
    print("  Excluded (NOT scored as failing):")
    for name, reason in p["excluded_criteria"].items():
        print(f"    - {name}: {reason}")

    a = result["altman_z_partial"]
    print("\n--- Altman Z''-Score (PARTIAL — informational only, official thresholds do NOT apply) ---")
    print(f"  X1 (Working Capital/Assets): {a['x1_working_capital_to_assets']}")
    print(f"  X3 (EBIT/Assets):            {a['x3_ebit_to_assets']}")
    print(f"  X4 (Equity/Liabilities):     {a['x4_equity_to_liabilities']}")
    print(f"  partial_z:                   {a['partial_z']}  <- NOT an official score, see note")

    b = result["balance_sheet_strength"]
    print(f"\n--- Balance-Sheet Strength (as of {b['period']}) ---")
    for k, v in b.get("metrics", {}).items():
        print(f"  {k:35s} = {v}")
    if b.get("warnings"):
        print(f"  WARNINGS: {b['warnings']}")

    e = result["earnings_consistency"]
    print(f"\n--- Earnings Consistency ({e['quarters_used']} quarters) ---")
    if e["note"]:
        print(f"  NOTE: {e['note']}")
    else:
        print(f"  mean NPM%: {e['mean_npm_pct']}  |  coefficient of variation: {e['coefficient_of_variation']}")


def save_financial_health(result: dict, company: str, filing_type: str) -> str:
    out_path = ANALYSIS_OUTPUT_DIR / f"{company}_{filing_type}_financial_health.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.analysis.financial_health <company_symbol> [consolidated|standalone]")
        sys.exit(1)
    company = sys.argv[1]
    filing_type = sys.argv[2] if len(sys.argv) > 2 else "consolidated"

    result = compute_financial_health(company, filing_type)
    print_financial_health(result)

    out_path = save_financial_health(result, company, filing_type)
    print(f"\nSaved to {out_path}")