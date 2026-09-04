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
    dedupe: bool = False,
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
        history = [_metric_row_to_dict(r) for r in rows]
        return _dedupe_history(history) if dedupe else history


def _dedupe_history(history: list[dict]) -> list[dict]:
    if not history:
        return []
    by_period: dict = {}
    order: list = []
    for row in history:
        period = row["period"]
        if period not in by_period:
            order.append(period)
            by_period[period] = row
        elif row["is_annual"] and not by_period[period]["is_annual"]:
            by_period[period] = row
        # else: an already-preferred (or equally-ranked) row is already stored -- keep it.
    return [by_period[p] for p in order]


def _pick_latest(history: list[dict]) -> dict | None:
    deduped = _dedupe_history(history)
    return deduped[-1] if deduped else None


def latest_metric(db_path: str | Path, symbol: str, filing_type: str, metric_name: str) -> dict | None:
    history = metric_history(db_path, symbol, filing_type, metric_name)
    return _pick_latest(history)


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
                     -- Same tiebreak as _pick_latest() above, done in SQL
                     -- since this query is itself a per-company "latest"
                     -- lookup: on a period_end tie, prefer the annual
                     -- filing (is_annual DESC puts 1 before 0) over
                     -- whichever row SQLite would otherwise return first.
                     ORDER BY COALESCE(f2.period_end, f2.instant) DESC, f2.is_annual DESC LIMIT 1
                 )
               ORDER BY m.value DESC""",
            (filing_type, metric_name),
        ).fetchall()
        return [
            {"symbol": r["company_symbol"], "period": r["period_end"] or r["instant"],
             "value": r["value"], "source_file": r["source_file"]}
            for r in rows
        ]


def fact_history(
    db_path: str | Path, symbol: str, filing_type: str, field_name: str, dedupe: bool = False
) -> list[dict]:
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
        history = [_metric_row_to_dict(r) for r in rows]
        return _dedupe_history(history) if dedupe else history


def latest_fact(db_path: str | Path, symbol: str, filing_type: str, field_name: str) -> dict | None:
    history = fact_history(db_path, symbol, filing_type, field_name)
    return _pick_latest(history)


def _metric_row_to_dict(r: sqlite3.Row) -> dict:
    return {
        "period": r["period_end"] or r["instant"],
        "value": r["value"],
        "context_id": r["context_id"],
        "source_file": r["source_file"],
        "is_single_quarter": bool(r["is_single_quarter"]),
        "is_annual": bool(r["is_annual"]),
    }