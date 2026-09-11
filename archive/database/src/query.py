import sys

from src.db import get_connection


def get_metric_history(symbol: str, filing_type: str, metric_name: str, single_quarter_only: bool = True):
    with get_connection() as conn:
        query = """
            SELECT f.period_end, f.instant, f.context_id, m.value
            FROM financial_metrics m
            JOIN filings f ON f.id = m.filing_id
            WHERE f.company_symbol = ? AND f.filing_type = ? AND m.metric_name = ?
        """
        params = [symbol, filing_type, metric_name]
        if single_quarter_only:
            query += " AND f.is_single_quarter = 1"
        query += " ORDER BY COALESCE(f.period_end, f.instant)"
        rows = conn.execute(query, params).fetchall()
        return [(r["period_end"] or r["instant"], r["value"]) for r in rows]


def get_latest_metric(symbol: str, filing_type: str, metric_name: str):
    """Most recent non-null value for one metric — e.g. current P/E."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT f.period_end, f.instant, m.value
               FROM financial_metrics m
               JOIN filings f ON f.id = m.filing_id
               WHERE f.company_symbol=? AND f.filing_type=? AND m.metric_name=?
               ORDER BY COALESCE(f.period_end, f.instant) DESC LIMIT 1""",
            (symbol, filing_type, metric_name),
        ).fetchone()
        return (row["period_end"] or row["instant"], row["value"]) if row else (None, None)


def get_all_companies_latest(metric_name: str, filing_type: str = "consolidated"):
    with get_connection() as conn:
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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.query <metric_name> [filing_type]")
        print("Example: python -m src.query npm_pct consolidated")
        sys.exit(1)
    metric = sys.argv[1]
    filing_type = sys.argv[2] if len(sys.argv) > 2 else "consolidated"

    print(f"--- Latest '{metric}' ({filing_type}) across all companies ---")
    for symbol, period, value in get_all_companies_latest(metric, filing_type):
        print(f"  {symbol:10s} {period:12s} {value:.2f}")
