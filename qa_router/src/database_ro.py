from __future__ import annotations

import sqlite3
from pathlib import Path


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def list_companies(db_path: str | Path) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT symbol, name, bse_scrip FROM companies ORDER BY symbol").fetchall()
        return [dict(r) for r in rows]


def metric_history(
    db_path: str | Path,
    symbol: str,
    filing_type: str,
    metric_name: str,
    single_quarter_only: bool = False,
) -> list[dict]:
    with _connect(db_path) as conn:
        query = """
            SELECT f.period_end, f.instant, f.context_id, f.source_file,
                   f.is_single_quarter, f.is_annual, m.value
            FROM financial_metrics m
            JOIN filings f ON f.id = m.filing_id
            WHERE f.company_symbol = ? AND f.filing_type = ? AND m.metric_name = ?
        """
        params: list = [symbol, filing_type, metric_name]
        if single_quarter_only:
            query += " AND f.is_single_quarter = 1"
        query += " ORDER BY COALESCE(f.period_end, f.instant)"
        rows = conn.execute(query, params).fetchall()
        return [_metric_row_to_dict(r) for r in rows]


def latest_metric(db_path: str | Path, symbol: str, filing_type: str, metric_name: str) -> dict | None:
    history = metric_history(db_path, symbol, filing_type, metric_name)
    return history[-1] if history else None


def all_companies_latest_metric(db_path: str | Path, metric_name: str, filing_type: str = "consolidated") -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT f.company_symbol, f.period_end, f.instant, f.source_file, m.value
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
        return [
            {"symbol": r["company_symbol"], "period": r["period_end"] or r["instant"],
             "value": r["value"], "source_file": r["source_file"]}
            for r in rows
        ]


def fact_history(db_path: str | Path, symbol: str, filing_type: str, field_name: str) -> list[dict]:
    """Raw-fact equivalent of metric_history() -- reads financial_facts
    (data_extraction's canonical values: revenue, net_profit, dividends,
    eps_basic, total_assets, ...) instead of financial_metrics
    (data_analysis's computed ratios/valuation). No query.py precedent
    exists for this -- query.py only ever reads financial_metrics."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT f.period_end, f.instant, f.context_id, f.source_file,
                      f.is_single_quarter, f.is_annual, ff.value
               FROM financial_facts ff
               JOIN filings f ON f.id = ff.filing_id
               WHERE f.company_symbol = ? AND f.filing_type = ? AND ff.field_name = ?
               ORDER BY COALESCE(f.period_end, f.instant)""",
            (symbol, filing_type, field_name),
        ).fetchall()
        return [_metric_row_to_dict(r) for r in rows]


def latest_fact(db_path: str | Path, symbol: str, filing_type: str, field_name: str) -> dict | None:
    history = fact_history(db_path, symbol, filing_type, field_name)
    return history[-1] if history else None


def _metric_row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "period": r["period_end"] or r["instant"],
        "value": r["value"],
        "context_id": r["context_id"],
        "source_file": r["source_file"],
        "is_single_quarter": bool(r["is_single_quarter"]),
        "is_annual": bool(r["is_annual"]),
    }
