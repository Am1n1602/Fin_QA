"""
data_analysis/src/analysis/peer_comparison.py

Stage 5 — Peer Comparison (roadmap Section 13 / Section 15).

Scope for this first pass:
  - User-supplied peer group (list of symbols) — no auto peer-detection yet.
  - Sector median / mean / percentile IS included, but "sector" here just
    means "the peer group you passed in" — the `companies` table has no
    `sector` column (see schema.sql), so there is nothing to derive this
    from automatically. If/when a `sector` column gets added to
    `companies`, this module doesn't need to change — the caller would
    just build `symbols` from a DB query instead of a hardcoded list.

IMPORTANT — why this file does NOT import database/src/query.py:
    This is a Python *module-name collision*, not a venv-isolation issue
    — there is one shared venv at the project root, covering
    data_extraction/, data_analysis/, and database/ alike. The problem is
    that `data_analysis/` and `database/` each have their own top-level
    package literally named `src` (this file is `data_analysis`'s
    `src.analysis.peer_comparison`; the target is `database`'s
    `src.query`, which itself does `from src.db import get_connection`).
    Python's module cache (`sys.modules`) can only hold one package named
    `src` at a time — whichever gets imported first "wins" that name, and
    the other's `import src.whatever` statements resolve against the
    wrong package (or fail outright). No amount of venv sharing or
    `sys.path` reordering fixes this on its own; the packages need
    distinct names, or the shared code needs to live outside both `src`
    trees.

    Rather than patch this with sys.path / importlib module-aliasing
    tricks — which would quietly re-couple two projects you've kept
    deliberately separate — this module talks to the SQLite file
    directly via the stdlib `sqlite3` module. `_all_companies_latest()`
    below is a deliberate, minimal re-implementation of
    `database/src/query.py`'s `get_all_companies_latest()` (same SQL).
    This is safe to duplicate because it's a read-only retrieval query,
    NOT a financial calculation — Section 6's "single source of truth"
    rule is about ratio/metric math (ROE, NPM, etc.), which this file
    never computes. All values here are loaded verbatim from
    `financial_metrics`, exactly as `database/` already guarantees.

    If this duplication ever becomes a maintenance problem, the real fix
    is a `shared/` sibling folder (NOT named `src`) holding just
    `get_connection`/`get_all_companies_latest`, which both `database`
    and `data_analysis` import by that distinct name — since there's
    already one shared venv, this is purely a naming/layout fix, no
    environment changes needed.

Usage:
    from src.analysis.peer_comparison import compare_peers

    result = compare_peers(
        symbols=["TCS", "INFY", "HCLTECH"],
        metric_names=["npm_pct", "roe_pct", "debt_to_equity", "pe_ratio"],
        filing_type="consolidated",
        db_path="path/to/financial_intelligence.db",
    )
"""

import json
import os
import sqlite3
import statistics
import sys
from datetime import datetime, timezone
from typing import Optional


# Direction each metric should be read in, per roadmap Section 15:
#   "ROE -> higher is better", "Debt/Equity -> lower is generally better",
#   "Do not assume that lower PE automatically means better investment
#   quality" (i.e. valuation multiples are 'neutral' — reported, not judged).
# Metrics not listed here default to "neutral" (see _direction()).
METRIC_DIRECTION = {
    # Profitability — higher is better
    "npm_pct": "higher",
    "pbt_margin_pct": "higher",
    "ebitda_margin_pct_approx": "higher",
    "roe_pct": "higher",
    "roce_pct": "higher",
    # Liquidity / coverage — higher is better
    "current_ratio": "higher",
    "interest_coverage_ratio": "higher",
    "asset_turnover": "higher",
    # Leverage / cost — lower is better
    "debt_to_equity": "lower",
    "effective_tax_rate_pct": "lower",
    "employee_cost_intensity_pct": "lower",
    "employee_cost_pct_of_total_expenses": "lower",
    "other_expenses_pct_of_revenue": "lower",
    # Valuation — neutral, never auto-judged (roadmap explicit warning)
    "pe_ratio": "neutral",
    "pb_ratio": "neutral",
    "ev_to_sales": "neutral",
    # Added this session alongside ratios.py/valuation.py's new metrics —
    # these predate ranking.py but were missing here, meaning they'd have
    # silently defaulted to "neutral" (wrong for most of them; unlike
    # pe_ratio, there's no principled reason to withhold judgment on
    # cash_ratio or roa_pct being higher-is-better).
    "roa_pct": "higher",
    "operating_roce_pct": "higher",
    "working_capital_to_assets_pct": "higher",
    "equity_to_liabilities_pct": "higher",
    "cash_ratio": "higher",
    "net_debt_to_operating_ebit": "lower",
    "earnings_yield_pct": "higher",
}


def _direction(metric_name: str) -> str:
    return METRIC_DIRECTION.get(metric_name, "neutral")


def _get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _all_companies_latest(conn: sqlite3.Connection, metric_name: str, filing_type: str):
    """Deliberate local re-implementation of database/src/query.py's
    get_all_companies_latest() — see module docstring for why this is
    duplicated rather than imported. Keep this in sync manually if that
    function's SQL ever changes."""
    rows = conn.execute(
        """SELECT f.company_symbol, f.period_end, f.instant, m.value
           FROM financial_metrics m
           JOIN filings f ON f.id = m.filing_id
           WHERE f.filing_type=? AND m.metric_name=?
             AND m.id = (
                 SELECT m2.id FROM financial_metrics m2
                 JOIN filings f2 ON f2.id = m2.filing_id
                 WHERE f2.company_symbol = f.company_symbol
                   AND f2.filing_type = f.filing_type
                   AND m2.metric_name = m.metric_name
                 ORDER BY COALESCE(f2.period_end, f2.instant) DESC LIMIT 1
             )
           ORDER BY m.value DESC""",
        (filing_type, metric_name),
    ).fetchall()
    return [(r["company_symbol"], r["period_end"] or r["instant"], r["value"]) for r in rows]


def _percentile(value: float, all_values: list, direction: str) -> float:
    """Percentile rank of `value` within `all_values`, direction-aware.
    Higher percentile always means 'more favourable' for higher/lower
    metrics. For neutral metrics this is just a raw rank-percentile with
    no favourable/unfavourable connotation (see module docstring)."""
    n = len(all_values)
    if n <= 1:
        return 100.0
    if direction == "lower":
        better_or_equal = sum(1 for v in all_values if v >= value)
    else:
        # 'higher' and 'neutral' both rank ascending-is-worse by default;
        # for 'neutral' this is just positional, not a quality judgment.
        better_or_equal = sum(1 for v in all_values if v <= value)
    return round(better_or_equal / n * 100, 1)


def compare_peers(
    symbols: list,
    metric_names: list,
    filing_type: str = "consolidated",
    db_path: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> dict:
    """Compare a user-supplied peer group across one or more metrics.

    Exactly one of `db_path` / `conn` must be provided. Pass an existing
    `conn` (sqlite3.Connection, row_factory=sqlite3.Row) if you already
    have one open elsewhere; otherwise pass `db_path` and this function
    manages its own connection.

    Returns:
        {
          "<metric_name>": {
            "direction": "higher" | "lower" | "neutral",
            "leader": "<symbol>" | None,       # None for 'neutral' metrics
            "leader_value": float | None,
            "highest": {"symbol": ..., "value": ...} | None,
            "lowest": {"symbol": ..., "value": ...} | None,
            "sector_median": float | None,
            "sector_mean": float | None,
            "companies": {
              "<symbol>": {
                "value": float | None,
                "period": str | None,
                "rank": int | None,            # 1 = highest raw value
                "percentile": float | None,
                "status": "ok" | "insufficient_data",
                "reason": str | None,
              },
              ...
            },
          },
          ...
        }

    Never fabricates values: a symbol missing from the DB for a given
    metric gets value=None, status="insufficient_data", and an explicit
    reason — it is excluded from median/mean/percentile math, never
    silently treated as zero (per roadmap Section 32).
    """
    if filing_type != "consolidated":
        # Policy decision (confirmed against real data): standalone figures
        # can be badly distorted by one-off items — e.g. HCLTECH standalone
        # npm_pct came back ~49% (leader) purely from a one-off Other Income
        # item, per data_analysis's own documented guidance to prefer
        # consolidated for genuine operating-performance comparisons.
        # Not blocked, just flagged loudly so it's never silently trusted
        # as equivalent to a consolidated comparison.
        print(
            f"NOTE: compare_peers() called with filing_type='{filing_type}' — "
            f"standalone figures are diagnostic only and may be distorted by "
            f"one-off items (e.g. subsidiary dividends). Do not feed standalone "
            f"results into Ranking (Stage 6) or Reports (Stage 8) without review.",
            file=sys.stderr,
        )

    if conn is None:
        if db_path is None:
            raise ValueError("compare_peers requires either db_path or conn")
        conn = _get_connection(db_path)
        owns_conn = True
    else:
        owns_conn = False

    try:
        results = {}
        for metric_name in metric_names:
            direction = _direction(metric_name)
            rows = _all_companies_latest(conn, metric_name, filing_type)
            by_symbol = {sym: (period, val) for sym, period, val in rows}

            present = []  # (symbol, period, value) for symbols in our peer group with a real value
            companies = {}
            for sym in symbols:
                if sym in by_symbol and by_symbol[sym][1] is not None:
                    period, val = by_symbol[sym]
                    present.append((sym, period, val))
                else:
                    companies[sym] = {
                        "value": None,
                        "period": None,
                        "rank": None,
                        "percentile": None,
                        "status": "insufficient_data",
                        "reason": f"{metric_name}_missing_for_{sym}_{filing_type}",
                    }

            values = [v for _, _, v in present]
            sector_median = statistics.median(values) if values else None
            sector_mean = round(statistics.mean(values), 4) if values else None

            highest = lowest = None
            leader = leader_value = None
            if present:
                highest_sym, _, highest_val = max(present, key=lambda r: r[2])
                lowest_sym, _, lowest_val = min(present, key=lambda r: r[2])
                highest = {"symbol": highest_sym, "value": highest_val}
                lowest = {"symbol": lowest_sym, "value": lowest_val}
                if direction == "higher":
                    leader, leader_value = highest_sym, highest_val
                elif direction == "lower":
                    leader, leader_value = lowest_sym, lowest_val
                # direction == "neutral" -> leader stays None on purpose
                # (roadmap: don't imply e.g. lowest PE = "winner")

            # rank by raw value, descending; ties share the same rank
            # (standard competition ranking, e.g. 1,2,2,4 — not 1,2,3,4).
            # Confirmed necessary against real data: TCS/INFY tie exactly
            # at debt_to_equity=0.0000 and must not be split into 2/3.
            ranked = sorted(present, key=lambda r: r[2], reverse=True)
            rank_by_symbol = {}
            current_rank = 0
            last_value = None
            for i, (sym, _, val) in enumerate(ranked):
                if val != last_value:
                    current_rank = i + 1
                rank_by_symbol[sym] = current_rank
                last_value = val

            for sym, period, val in present:
                companies[sym] = {
                    "value": val,
                    "period": period,
                    "rank": rank_by_symbol[sym],
                    "percentile": _percentile(val, values, direction),
                    "status": "ok",
                    "reason": None,
                }

            results[metric_name] = {
                "direction": direction,
                "leader": leader,
                "leader_value": leader_value,
                "highest": highest,
                "lowest": lowest,
                "sector_median": sector_median,
                "sector_mean": sector_mean,
                "companies": companies,
            }

        return results
    finally:
        if owns_conn:
            conn.close()


def print_comparison(result: dict, symbols: list) -> None:
    """Simple terminal table, one block per metric — for quick eyeballing
    against real DB output before this gets wired into anything else."""
    for metric_name, data in result.items():
        print(f"\n--- {metric_name} ({data['direction']}) ---")
        if data["sector_median"] is not None:
            print(f"  peer_median={data['sector_median']:.4f}  peer_mean={data['sector_mean']:.4f}", end="")
            if data["leader"]:
                print(f"  leader={data['leader']} ({data['leader_value']:.4f})")
            else:
                print(f"  highest={data['highest']['symbol']} ({data['highest']['value']:.4f})"
                      f"  lowest={data['lowest']['symbol']} ({data['lowest']['value']:.4f})  [neutral metric]")
        else:
            print("  no peer had data for this metric")

        for sym in symbols:
            c = data["companies"].get(sym, {"status": "insufficient_data", "value": None})
            if c["status"] == "ok":
                print(f"    {sym:10s} value={c['value']:>10.4f}  rank={c['rank']}  percentile={c['percentile']}")
            else:
                print(f"    {sym:10s} value=      None  status={c['status']}  reason={c.get('reason')}")


def save_comparison(
    result: dict,
    symbols: list,
    filing_type: str,
    output_dir: str = "data/processed/peer_comparison",
) -> str:
    """Persist a compare_peers() result to disk as JSON.

    ASSUMPTION FLAGGED: I don't have visibility into the exact file-naming
    / directory convention data_extraction's run_extraction.py or
    data_analysis's combine_and_analyze.py already use for their processed
    output — PROJECT_STATUS.md documents them functionally but not their
    literal output paths. `output_dir` defaults to
    'data/processed/peer_comparison' (relative to wherever this runs from
    — i.e. data_analysis/ when invoked via the CLI below), which matches
    the roadmap's data/processed/ convention but may not match what the
    other two modules actually do on disk. Override output_dir to match
    if it doesn't — this is a one-parameter change, nothing else in this
    module depends on the path.

    Filename: peer_comparison_<filing_type>_<SYM1-SYM2-...>.json (sorted
    symbols, so the same peer group always overwrites the same file
    instead of accumulating timestamped duplicates — mirrors how
    financial_metrics itself is idempotent/re-runnable per PROJECT_STATUS).

    Returns the path written.
    """
    os.makedirs(output_dir, exist_ok=True)
    symbol_slug = "-".join(sorted(symbols))
    filename = f"peer_comparison_{filing_type}_{symbol_slug}.json"
    path = os.path.join(output_dir, filename)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filing_type": filing_type,
        "symbols": symbols,
        "metrics": result,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    return path


if __name__ == "__main__":
    # python -m src.analysis.peer_comparison <db_path> <filing_type> <symbol1,symbol2,...> <metric1,metric2,...>
    # Example:
    #   python -m src.analysis.peer_comparison ../database/data/financial_intelligence.db \
    #       consolidated TCS,INFY,HCLTECH npm_pct,roe_pct,debt_to_equity,pe_ratio
    if len(sys.argv) < 5:
        print("Usage: python -m src.analysis.peer_comparison <db_path> <filing_type> <sym1,sym2,...> <metric1,metric2,...>")
        sys.exit(1)

    _db_path, _filing_type, _symbols_arg, _metrics_arg = sys.argv[1:5]
    _symbols = [s.strip() for s in _symbols_arg.split(",")]
    _metrics = [m.strip() for m in _metrics_arg.split(",")]

    _result = compare_peers(_symbols, _metrics, filing_type=_filing_type, db_path=_db_path)
    print_comparison(_result, _symbols)

    _saved_path = save_comparison(_result, _symbols, _filing_type)
    print(f"\nSaved to {_saved_path}")