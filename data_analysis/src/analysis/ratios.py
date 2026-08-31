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
            _safe_div(
                (r.get("borrowings_current") or 0) + (r.get("borrowings_noncurrent") or 0),
                r.get("total_equity"),
                as_pct=False,
            )
        ),
        "roe_pct": _safe_div(r.get("net_profit"), r.get("total_equity")),
        "roce_pct": (
            None if None in (r.get("pbt_before_exceptional"), r.get("total_assets"), r.get("current_liabilities")) else
            _safe_div(
                r["pbt_before_exceptional"] + (r.get("finance_costs") or 0),
                r["total_assets"] - r["current_liabilities"],
            )
        ),
        "asset_turnover": _safe_div(revenue, r.get("total_assets"), as_pct=False),
    }

    # Approximate EBITDA margin: PBT before exceptional items, add back
    # D&A and finance costs (non-operating financing cost), subtract
    # other income (non-operating). This is an approximation — other
    # income is assumed purely non-operating, which is usually but not
    # always exactly true; treat as directional, not exact.
    if None not in (r.get("pbt_before_exceptional"), depreciation, other_income) and revenue:
        ebitda_approx = r["pbt_before_exceptional"] + depreciation + finance_costs - other_income
        ratios["ebitda_margin_pct_approx"] = (ebitda_approx / revenue) * 100
    else:
        ratios["ebitda_margin_pct_approx"] = None

    return ratios


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
        entry = {
            "from_period": f"{prev.get('period_start')} to {prev.get('period_end')}",
            "to_period": f"{curr.get('period_start')} to {curr.get('period_end')}",
        }
        for field in ("revenue", "net_profit", "pbt", "total_expenses"):
            prev_val = prev.get(field)
            curr_val = curr.get(field)
            if prev_val is not None and prev_val <= 0:
                # Growth % from a zero/negative base is mathematically
                # correct but not meaningful (e.g. -880% when the prior
                # quarter itself was a loss) — report the raw change
                # instead of a misleading percentage.
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


def analyze(canonical_records: list[dict]) -> dict:
    """Full analysis output for one company/filing-type: ratios per
    period plus trends across periods (if applicable)."""
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
    }


# Fields that are NOT plain percentages — used by both this file's __main__
# and combine_and_analyze.py's __main__ so display formatting stays
# consistent everywhere this data gets printed.
_RATIO_UNIT_OVERRIDES = {
    "interest_coverage_ratio": "x",       # e.g. "45.2x" — a multiple, not a %
    "shares_outstanding": "count",
    "operating_leverage_signal": "pp",    # percentage-point spread, not itself a %
    "current_ratio": "x",
    "debt_to_equity": "x",
    "asset_turnover": "x",
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
