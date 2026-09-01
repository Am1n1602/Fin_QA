import json
import sys
from datetime import date
from pathlib import Path

def _safe_div(numerator, denominator, as_pct: bool = True):
    if numerator is None or denominator in (None, 0):
        return None
    result = numerator / denominator
    return result * 100 if as_pct else result


def _duration_days(record: dict) -> int | None:
    ps, pe = record.get("period_start"), record.get("period_end")
    if not ps or not pe:
        return None
    try:
        return (date.fromisoformat(pe[:10]) - date.fromisoformat(ps[:10])).days
    except (ValueError, TypeError):
        return None


def _is_single_quarter(record: dict, tolerance: int = 20) -> bool:
    days = _duration_days(record)
    return days is not None and abs(days - 91) <= tolerance


def _is_annual(record: dict, tolerance: int = 20) -> bool:
    days = _duration_days(record)
    return days is not None and abs(days - 365) <= tolerance


def compute_ebit(record: dict):
    """EBIT = Profit Before Tax (before exceptional items) + Finance
    Costs added back. This is a real accounting identity (PBT = EBIT -
    Interest, given Ind AS Finance Costs is the interest-expense line),
    not an approximation — both inputs are tagged canonical fields.
    Exceptional items are deliberately excluded (using
    pbt_before_exceptional rather than pbt) to keep EBIT reflecting
    ongoing operations rather than one-off gains/losses — a modeling
    choice, documented here rather than silently baked in.
    """
    pbt_before_exceptional = record.get("pbt_before_exceptional")
    if pbt_before_exceptional is None:
        return None
    return pbt_before_exceptional + (record.get("finance_costs") or 0)


def operating_ebit(record: dict):
    """EBIT with Other Income excluded, unlike compute_ebit() above.
    Same exact-identity logic: Revenue - Employee Expense - Depreciation
    - Other Expenses (no Finance Costs, no Other Income). This matters
    because compute_ebit()/roce_pct's Other-Income-inclusive figure can
    be inflated by one-off items — confirmed this session with
    HCLTECH's standalone npm_pct hitting ~49% from a one-off Other
    Income line (likely a subsidiary dividend upstream). A ranking
    formula built on that inflated number would reward a company for
    something unrelated to ongoing business quality, so this version
    exists specifically for that use case (see operating_roce_pct and
    net_debt_to_operating_ebit below).
    """
    revenue = record.get("revenue")
    employee_expense = record.get("employee_expense")
    depreciation = record.get("depreciation")
    other_expenses = record.get("other_expenses")
    if None in (revenue, employee_expense, depreciation, other_expenses):
        return None
    return revenue - employee_expense - depreciation - other_expenses


def compute_total_debt(record: dict):
    """Total Debt = Current Borrowings + Non-current Borrowings. Absent
    borrowings tags default to 0 — genuinely debt-free companies
    (common among large IT services firms) simply have no borrowings
    tag at all, the same convention debt_to_equity has always used.

    Shared by debt_to_equity, total_debt_to_assets_pct, and
    compute_net_debt below, plus valuation.py's
    compute_enterprise_value — this was independently re-derived in
    four places before consolidating here into one definition.
    """
    return (record.get("borrowings_current") or 0) + (record.get("borrowings_noncurrent") or 0)


def compute_capex(record: dict):
    """Combined Capex = Purchase of PP&E + Purchase of Intangible Assets
    (both from the cash flow statement's investing activities section).
    """
    ppe = record.get("capex_ppe")
    intangibles = record.get("capex_intangibles")
    if ppe is None and intangibles is None:
        return None
    return (ppe or 0) + (intangibles or 0)


def compute_net_debt(record: dict):
    """Net Debt = Total Debt - Cash and Cash Equivalents. Borrowings
    absent on a record defaults to 0 (matches debt_to_equity's existing
    convention — genuinely debt-free IT companies have no borrowings tag
    at all). Cash absent returns None, NOT 0 — a missing cash figure is
    a data gap, not evidence of zero cash, and defaulting it would
    silently overstate net debt.

    """
    if record.get("cash_and_equivalents") is None:
        return None
    return compute_total_debt(record) - record["cash_and_equivalents"]


def compute_period_ratios(record: dict) -> dict:
    """Compute P&L ratios for one period record (one context/quarter)."""
    r = record  # short alias
    finance_costs = r.get("finance_costs") or 0  # many IT/debt-free companies won't have this tag at all — treat absent as 0, not unknown
    depreciation = r.get("depreciation")
    other_income = r.get("other_income")
    revenue = r.get("revenue")

    ratios = {
        "npm_pct": _safe_div(r.get("net_profit"), revenue),
        "pbt_margin_pct": _safe_div(r.get("pbt"), revenue),
        "effective_tax_rate_pct": _safe_div(r.get("tax_expense"), r.get("pbt")),
        "other_income_pct_of_total_income": _safe_div(other_income, r.get("total_income")),
        "exceptional_items_pct_of_pbt_before_exceptional": _safe_div(
            r.get("exceptional_items"), r.get("pbt_before_exceptional")
        ),

        # --- Cost structure ---
        "employee_cost_intensity_pct": _safe_div(r.get("employee_expense"), revenue),
        "employee_cost_pct_of_total_expenses": _safe_div(r.get("employee_expense"), r.get("total_expenses")),
        "other_expenses_pct_of_revenue": _safe_div(r.get("other_expenses"), revenue),

        "interest_coverage_ratio": (
            None if not finance_costs else
            _safe_div(r.get("pbt_before_exceptional"), finance_costs, as_pct=False)
        ),

        # --- Consolidated-entity structure ---
        "minority_interest_pct_of_net_profit": _safe_div(r.get("net_profit_nci"), r.get("net_profit")),

        # --- Share count (not a %, a count) ---
        "shares_outstanding": _safe_div(r.get("paid_up_equity_capital"), r.get("face_value_per_share"), as_pct=False),
        "current_ratio": _safe_div(r.get("current_assets"), r.get("current_liabilities"), as_pct=False),
        "debt_to_equity": (
            None if r.get("total_equity") is None else
            _safe_div(compute_total_debt(r), r.get("total_equity"), as_pct=False)
        ),
        "roe_pct": _safe_div(r.get("net_profit"), r.get("total_equity")),
        "roce_pct": (
            None if None in (r.get("total_assets"), r.get("current_liabilities")) or compute_ebit(r) is None else
            _safe_div(compute_ebit(r), r["total_assets"] - r["current_liabilities"])
        ),
        "asset_turnover": _safe_div(revenue, r.get("total_assets"), as_pct=False),

        "roa_pct": _safe_div(r.get("net_profit"), r.get("total_assets")),
        "working_capital_to_assets_pct": (
            None if None in (r.get("current_assets"), r.get("current_liabilities"), r.get("total_assets")) else
            _safe_div(r["current_assets"] - r["current_liabilities"], r["total_assets"])
        ),
        "equity_to_liabilities_pct": _safe_div(r.get("total_equity"), r.get("total_liabilities")),
        "ebit": compute_ebit(r),  # currency amount, not a % — see _RATIO_UNIT_OVERRIDES
    }

    op_ebit = operating_ebit(r)
    net_debt = compute_net_debt(r)

    ratios["cash_ratio"] = _safe_div(r.get("cash_and_equivalents"), r.get("current_liabilities"), as_pct=False)
    ratios["total_debt_to_assets_pct"] = (
        None if r.get("total_assets") is None else
        _safe_div(compute_total_debt(r), r.get("total_assets"))
    )
    ratios["net_debt"] = net_debt  # currency amount
    ratios["operating_ebit"] = op_ebit  # currency amount — Other-Income-excluded EBIT, see function docstring
    ratios["operating_roce_pct"] = (
        None if None in (r.get("total_assets"), r.get("current_liabilities")) or op_ebit is None else
        _safe_div(op_ebit, r["total_assets"] - r["current_liabilities"])
    )
    ratios["net_debt_to_operating_ebit"] = (
        None if net_debt is None or not op_ebit else
        _safe_div(net_debt, op_ebit, as_pct=False)
    )

    ratios["longterm_leverage_pct"] = (
        None if r.get("total_assets") is None else
        _safe_div(r.get("borrowings_noncurrent") or 0, r["total_assets"])
    )  # absent borrowings_noncurrent treated as 0, matching compute_total_debt's debt-free-company convention
    ratios["ebit_to_assets_pct"] = (
        None if r.get("total_assets") is None or compute_ebit(r) is None else
        _safe_div(compute_ebit(r), r["total_assets"])
    )
    ratios["cfo_pct"] = _safe_div(r.get("operating_cash_flow"), r.get("total_assets"))

    ratios["payout_ratio_pct"] = _safe_div(r.get("dividends"), r.get("net_profit"))
    ratios["capex"] = compute_capex(r)  # currency amount — see compute_capex()'s docstring for the None-vs-0 handling

    if None not in (r.get("pbt_before_exceptional"), depreciation, other_income) and revenue:
        ebitda_approx = r["pbt_before_exceptional"] + depreciation + finance_costs - other_income
        ratios["ebitda_margin_pct_approx"] = (ebitda_approx / revenue) * 100
    else:
        ratios["ebitda_margin_pct_approx"] = None

    return ratios


def _compute_period_growth(prev: dict, curr: dict, fields: tuple) -> dict:
    """Growth from `prev` to `curr` for each field in `fields`. Shared by
    compute_trends() (quarter-over-quarter) and compute_annual_yoy()
    (year-over-year) below — same negative/zero-base handling either
    way: percentage growth from a non-positive prior value isn't
    meaningful (e.g. -880% when the prior period itself was a loss), so
    it's reported as None + the raw absolute change + an explanatory
    note instead of a misleading percentage."""
    entry = {
        "from_period": f"{prev.get('period_start')} to {prev.get('period_end')}",
        "to_period": f"{curr.get('period_start')} to {curr.get('period_end')}",
    }
    for field in fields:
        prev_val = prev.get(field)
        curr_val = curr.get(field)
        if prev_val is not None and prev_val <= 0:
            entry[f"{field}_growth_pct"] = None
            entry[f"{field}_change_absolute"] = (
                curr_val - prev_val if curr_val is not None else None
            )
            entry[f"{field}_growth_note"] = "prior period was zero/negative — % not meaningful, see absolute change"
        else:
            entry[f"{field}_growth_pct"] = _safe_div(
                (curr_val - prev_val) if None not in (curr_val, prev_val) else None,
                prev_val,
            )
    return entry


def compute_trends(records: list[dict]) -> list[dict]:
    """
    Only compares single-quarter (~3 month) periods against each other —
    excludes YTD/cumulative and annual-duration contexts, which can share
    a period_end with a real quarterly context.
    """
    quarterly = [r for r in records if _is_single_quarter(r)]
    quarterly.sort(key=lambda r: (r.get("period_start") or "", r.get("period_end") or ""))

    trends = []
    for prev, curr in zip(quarterly, quarterly[1:]):
        entry = _compute_period_growth(prev, curr, ("revenue", "net_profit", "pbt", "total_expenses"))

        # Operating leverage signal: is revenue growing faster than costs?
        # Positive = margin tailwind (revenue outpacing expense growth),
        # negative = margin pressure. None if either growth % wasn't
        # meaningful (see negative-base handling above).
        rev_g, exp_g = entry.get("revenue_growth_pct"), entry.get("total_expenses_growth_pct")
        entry["operating_leverage_signal"] = (
            rev_g - exp_g if None not in (rev_g, exp_g) else None
        )

        trends.append(entry)
    return trends


def compute_annual_yoy(records: list[dict]) -> dict | None:
    """Real single-year year-over-year growth, using the 2 most recent.

    Returns None if fewer than 2 real annual periods exist yet.
    """
    annual = [r for r in records if _is_annual(r)]
    annual.sort(key=lambda r: r.get("period_end") or "", reverse=True)
    if len(annual) < 2:
        return None

    latest, prior = annual[0], annual[1]
    entry = _compute_period_growth(
        prior, latest, ("revenue", "net_profit", "pbt", "total_expenses", "eps_basic")
    )
    entry["latest_period_end"] = latest.get("period_end")
    entry["prior_period_end"] = prior.get("period_end")
    return entry


def analyze(canonical_records: list[dict]) -> dict:
    """Full analysis output for one company/filing-type: ratios per
    period, quarter-over-quarter trends, and (once 2 annual periods
    exist) real year-over-year growth."""
    enriched = []
    for record in canonical_records:
        ratios = compute_period_ratios(record)
        merged = dict(record)
        merged["ratios"] = ratios
        merged["_ratio_gaps"] = [k for k, v in ratios.items() if v is None]
        enriched.append(merged)

    return {
        "periods": enriched,
        "trends": compute_trends(canonical_records),
        "annual_yoy": compute_annual_yoy(canonical_records),
    }


_RATIO_UNIT_OVERRIDES = {
    "interest_coverage_ratio": "x",       # e.g. "45.2x" — a multiple, not a %
    "shares_outstanding": "count",
    "operating_leverage_signal": "pp",    # percentage-point spread, not itself a %
    "current_ratio": "x",
    "debt_to_equity": "x",
    "asset_turnover": "x",
    "ebit": "currency",
    "cash_ratio": "x",
    "net_debt": "currency",
    "operating_ebit": "currency",
    "net_debt_to_operating_ebit": "x",
    "capex": "currency",
}


def format_ratio_value(key: str, value) -> str:
    if value is None:
        return "N/A"
    if key.endswith("_growth_note"):
        return str(value)
    if key.endswith("_change_absolute"):
        return f"{value:+,.0f}"  # raw ₹ amount
    unit = _RATIO_UNIT_OVERRIDES.get(key)
    if unit == "x":
        return f"{value:.2f}x"
    if unit == "count":
        return f"{value:,.0f}"
    if unit == "pp":
        return f"{value:+.2f}pp"
    if unit == "currency":
        return f"{value:,.0f}"
    return f"{value:+.2f}%" if key.endswith(("_growth_pct",)) else f"{value:.2f}%"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.analysis.ratios <path-to-{company}_{type}_canonical.json>")
        sys.exit(1)

    canonical_path = Path(sys.argv[1])
    canonical_records = json.loads(canonical_path.read_text())
    result = analyze(canonical_records)

    out_path = Path("data/analysis") / canonical_path.name.replace("_canonical.json", "_ratios.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"Saved to {out_path}\n")

    for p in result["periods"]:
        label = f"{p.get('period_start')} to {p.get('period_end')}" if p.get("period_start") else (p.get("period_end") or p.get("instant"))
        print(f"--- period={label} (context={p['context_id']}) ---")
        for k, v in p["ratios"].items():
            print(f"  {k:50s} = {format_ratio_value(k, v)}")
        print()

    if result["trends"]:
        print("--- Period-over-period trends ---")
        for t in result["trends"]:
            print(f"{t['from_period']} -> {t['to_period']}")
            for k, v in t.items():
                if k in ("from_period", "to_period"):
                    continue
                print(f"  {k:30s} = {format_ratio_value(k, v)}")
    else:
        print("(Only one period available — no trend to compute yet. "
              "Re-run this after your next quarterly pipeline run, or "
              "once a filing with a comparative period is mapped.)")