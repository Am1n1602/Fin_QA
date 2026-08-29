import json
import sys
from pathlib import Path

from datetime import date


def _safe_div(numerator, denominator, as_pct: bool = True):
    if numerator is None or denominator in (None, 0):
        return None
    result = numerator / denominator
    return result * 100 if as_pct else result


def compute_period_ratios(record: dict) -> dict:
    """Compute P&L ratios for one period record (one context/quarter)."""
    r = record  # short alias
    finance_costs = r.get("finance_costs") or 0 
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
    }

    # Approximate EBITDA margin: PBT before exceptional items, add back
    # D&A and finance costs (non-operating financing cost), subtract
    # other income (non-operating). This is an approximation — other
    # income is assumed purely non-operating, which is usually but not
    # always exactly true; treat as directional, not exact.

    # Need to fix this ->
    if None not in (r.get("pbt_before_exceptional"), depreciation, other_income) and revenue:
        ebitda_approx = r["pbt_before_exceptional"] + depreciation + finance_costs - other_income
        ratios["ebitda_margin_pct_approx"] = (ebitda_approx / revenue) * 100
    else:
        ratios["ebitda_margin_pct_approx"] = None

    return ratios

def _duration_days(record: dict) -> int | None:
    ps, pe = record.get("period_start"), record.get("period_end")
    if not ps or not pe:
        return None
    try:
        return (date.fromisoformat(pe[:10]) - date.fromisoformat(ps[:10])).days
    except (ValueError, TypeError):
        return None


def _is_single_quarter(record: dict, tolerance: int = 20) -> bool:
    """True only for ~3-month duration periods. Filters out YTD/cumulative
    and full-year contexts (e.g. Ind AS 'FourD'-style contexts) that would
    otherwise share a period_end with a real quarterly context and get
    wrongly compared against it."""
    days = _duration_days(record)
    return days is not None and abs(days - 91) <= tolerance


def compute_trends(records: list[dict]) -> list[dict]:
    """
    Only compares single-quarter (~3 month) periods against each other.
    Explicitly excludes YTD/cumulative and annual-duration contexts,
    which can share a period_end with a real quarterly context and would
    otherwise get zipped together as if consecutive — comparing a 9-month
    cumulative figure against a single quarter, for example.
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
            entry[f"{field}_growth_pct"] = _safe_div(
                (curr.get(field) - prev.get(field)) if None not in (curr.get(field), prev.get(field)) else None,
                prev.get(field),
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
            display = f"{v:.2f}%" if v is not None else "N/A (missing input)"
            print(f"  {k:50s} = {display}")
        print()

    if result["trends"]:
        print("--- Period-over-period trends ---")
        for t in result["trends"]:
            print(f"{t['from_period']} -> {t['to_period']}")
            for k, v in t.items():
                if k in ("from_period", "to_period"):
                    continue
                display = f"{v:+.2f}%" if v is not None else "N/A"
                print(f"  {k:30s} = {display}")
    else:
        print("(Only one period available — no trend to compute yet. "
              "Re-run this after your next quarterly pipeline run, or "
              "once a filing with a comparative period is mapped.)")
