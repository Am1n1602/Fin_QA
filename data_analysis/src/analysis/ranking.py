"""
Usage:
    from src.analysis.ranking import compute_rankings

    result = compute_rankings(
        symbols=["TCS", "INFY", "HCLTECH"],
        filing_type="consolidated",
        db_path="path/to/financial_intelligence.db",
    )
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

from src.analysis.peer_comparison import compare_peers, _percentile, _get_connection


RANKING_CATEGORIES = {
    "profitability": {
        "weight": 0.25,
        "metrics": ["roa_pct", "npm_pct", "roe_pct"],
    },
    "capital_efficiency": {
        "weight": 0.25,
        "metrics": ["operating_roce_pct"],
    },
    "safety": {
        "weight": 0.25,
        "metrics": [
            "working_capital_to_assets_pct",   # Altman X1 analogue
            "equity_to_liabilities_pct",       # Altman X4 analogue (book value, not market)
            "debt_to_equity",
            "current_ratio",
            "cash_ratio",
            "interest_coverage_ratio",
            "net_debt_to_operating_ebit",
        ],
    },
    "valuation": {
        "weight": 0.25,
        "metrics": ["earnings_yield_pct", "pe_ratio", "pb_ratio", "ev_to_sales"],
    },
}

VALUATION_LOWER_IS_BETTER = {"pe_ratio", "pb_ratio", "ev_to_sales"}


def _all_ranking_metrics() -> list:
    seen = []
    for cat in RANKING_CATEGORIES.values():
        for m in cat["metrics"]:
            if m not in seen:
                seen.append(m)
    return seen


def compute_rankings(
    symbols: list,
    filing_type: str = "consolidated",
    db_path: Optional[str] = None,
    conn=None,
    category_weights: Optional[dict] = None,
) -> dict:
    """Rank a peer group across the 4 categories above.

    Exactly one of db_path / conn must be provided — same convention as
    compare_peers(). If conn is passed, it's reused for the single
    compare_peers() call this makes (one query per metric internally,
    not one per category — no redundant round-trips).

    category_weights: optional dict overriding the default equal 25%
    split, e.g. {"profitability": 0.4, "capital_efficiency": 0.2,
    "safety": 0.3, "valuation": 0.1} — must sum to 1.0.

    Returns:
        {
          "<symbol>": {
            "category_scores": {"profitability": 82.3, ...} | None per category,
            "category_metrics_used": {
              "profitability": {"used": [...], "missing": [...]},
              ...
            },
            "composite_score": float | None,
            "rank": int | None,   # 1 = best; ties share a rank (see peer_comparison.py)
          },
          ...
        }

    Missing-data policy (per project decision): if a company is missing
    some metrics within a category, the category score is the average of
    whichever metrics ARE available for that company — renormalized, not
    silently treated as 0 and not blocking the whole category. If a
    company has zero available metrics in a category, that category's
    score is None for that company, and the composite renormalizes across
    whichever categories DO have a score — same principle, one level up.
    A company with zero scored categories gets composite_score=None and
    rank=None, not a fabricated last-place score.
    """
    if category_weights is None:
        category_weights = {cat: c["weight"] for cat, c in RANKING_CATEGORIES.items()}
    else:
        total = sum(category_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"category_weights must sum to 1.0, got {total}")
        missing_cats = set(RANKING_CATEGORIES) - set(category_weights)
        if missing_cats:
            raise ValueError(f"category_weights missing categories: {missing_cats}")

    owns_conn = False
    if conn is None:
        if db_path is None:
            raise ValueError("compute_rankings requires either db_path or conn")
        conn = _get_connection(db_path)
        owns_conn = True

    try:
        all_metrics = _all_ranking_metrics()
        peer_result = compare_peers(symbols, all_metrics, filing_type=filing_type, conn=conn)
        percentiles = {}  # percentiles[metric][symbol] -> float | None
        for metric, data in peer_result.items():
            percentiles[metric] = {}
            if metric in VALUATION_LOWER_IS_BETTER:
                ok_values = [c["value"] for c in data["companies"].values() if c["status"] == "ok"]
                for sym, c in data["companies"].items():
                    percentiles[metric][sym] = (
                        _percentile(c["value"], ok_values, "lower") if c["status"] == "ok" else None
                    )
            else:
                for sym, c in data["companies"].items():
                    percentiles[metric][sym] = c["percentile"]  # already correctly direction-scored

        results = {}
        for sym in symbols:
            category_scores = {}
            category_metrics_used = {}
            for cat_name, cat_def in RANKING_CATEGORIES.items():
                used, missing, available_pctiles = [], [], []
                for m in cat_def["metrics"]:
                    p = percentiles[m].get(sym)
                    if p is None:
                        missing.append(m)
                    else:
                        used.append(m)
                        available_pctiles.append(p)
                category_scores[cat_name] = (
                    round(sum(available_pctiles) / len(available_pctiles), 1) if available_pctiles else None
                )
                category_metrics_used[cat_name] = {"used": used, "missing": missing}

            scored_cats = [(cat, score) for cat, score in category_scores.items() if score is not None]
            if scored_cats:
                weight_sum = sum(category_weights[cat] for cat, _ in scored_cats)
                composite = round(
                    sum(category_weights[cat] * score for cat, score in scored_cats) / weight_sum, 1
                )
            else:
                composite = None

            results[sym] = {
                "category_scores": category_scores,
                "category_metrics_used": category_metrics_used,
                "composite_score": composite,
            }
        scored_syms = sorted(
            (s for s in symbols if results[s]["composite_score"] is not None),
            key=lambda s: results[s]["composite_score"],
            reverse=True,
        )
        current_rank, last_score = 0, None
        for i, sym in enumerate(scored_syms):
            score = results[sym]["composite_score"]
            if score != last_score:
                current_rank = i + 1
            results[sym]["rank"] = current_rank
            last_score = score
        for sym in symbols:
            if sym not in scored_syms:
                results[sym]["rank"] = None

        return results
    finally:
        if owns_conn:
            conn.close()


def _fmt_score(value) -> str:
    return f"{value:.1f}" if value is not None else "N/A"


def print_rankings(result: dict, symbols: list) -> None:
    """Terminal table, sorted by rank — for eyeballing against real DB
    output, same pattern as peer_comparison.py's print_comparison()."""
    ordered = sorted(
        symbols,
        key=lambda s: (result[s]["rank"] is None, result[s]["rank"] if result[s]["rank"] is not None else 0),
    )
    print(f"\n{'Rank':<6}{'Symbol':<10}{'Composite':<12}"
          + "".join(f"{cat:<20}" for cat in RANKING_CATEGORIES))
    for sym in ordered:
        r = result[sym]
        rank_str = str(r["rank"]) if r["rank"] is not None else "N/A"
        comp_str = _fmt_score(r["composite_score"])
        cat_strs = "".join(f"{_fmt_score(r['category_scores'][cat]):<20}" for cat in RANKING_CATEGORIES)
        print(f"{rank_str:<6}{sym:<10}{comp_str:<12}{cat_strs}")

    print("\n--- Missing metrics by category (transparency, not hidden) ---")
    for sym in ordered:
        gaps = {cat: v["missing"] for cat, v in result[sym]["category_metrics_used"].items() if v["missing"]}
        if gaps:
            print(f"  {sym}: {gaps}")


def save_rankings(
    result: dict,
    symbols: list,
    filing_type: str,
    output_dir: str = "data/processed/ranking",
) -> str:
    os.makedirs(output_dir, exist_ok=True)
    symbol_slug = "-".join(sorted(symbols))
    filename = f"ranking_{filing_type}_{symbol_slug}.json"
    path = os.path.join(output_dir, filename)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filing_type": filing_type,
        "symbols": symbols,
        "category_weights": {cat: c["weight"] for cat, c in RANKING_CATEGORIES.items()},
        "rankings": result,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return path


if __name__ == "__main__":
    # python -m src.analysis.ranking <db_path> <filing_type> <sym1,sym2,...>
    # Example:
    #   python -m src.analysis.ranking ../database/data/financial_intelligence.db \
    #       consolidated TCS,INFY,HCLTECH
    if len(sys.argv) < 4:
        print("Usage: python -m src.analysis.ranking <db_path> <filing_type> <sym1,sym2,...>")
        sys.exit(1)

    _db_path, _filing_type, _symbols_arg = sys.argv[1:4]
    _symbols = [s.strip() for s in _symbols_arg.split(",")]

    _result = compute_rankings(_symbols, filing_type=_filing_type, db_path=_db_path)
    print_rankings(_result, _symbols)

    _saved_path = save_rankings(_result, _symbols, _filing_type)
    print(f"\nSaved to {_saved_path}")