"""
Usage: python -m src.load_data [company_symbol]
       (no argument = load every company found in data_extraction/data/extracted/)
"""
import csv
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from src.config import EXTRACTED_DIR, ANALYSIS_DIR, PRICES_DIR, COMPANY_NAMES
from src.db import get_connection, init_db


def _duration_days(period_start, period_end) -> int | None:
    if not period_start or not period_end:
        return None
    try:
        return (date.fromisoformat(period_end[:10]) - date.fromisoformat(period_start[:10])).days
    except (ValueError, TypeError):
        return None

def _classify_duration(period_start, period_end) -> tuple[bool, bool]:
    days = _duration_days(period_start, period_end)
    if days is None:
        return False, False
    return abs(days - 91) <= 20, abs(days - 365) <= 20

def upsert_company(conn, symbol: str):
    conn.execute(
        "INSERT INTO companies (symbol, name) VALUES (?, ?) "
        "ON CONFLICT(symbol) DO UPDATE SET name=excluded.name",
        (symbol, COMPANY_NAMES.get(symbol, symbol)),
    )

def upsert_filing(conn, symbol: str, filing_type: str, record: dict, source_file: str) -> int:
    context_id = record["context_id"]
    period_start = record.get("period_start")
    period_end = record.get("period_end")
    instant = record.get("instant")
    is_sq, is_ann = _classify_duration(period_start, period_end)
    has_bs = record.get("total_assets") is not None

    conn.execute(
        "INSERT INTO filings "
        "(company_symbol, filing_type, context_id, period_start, period_end, instant, "
        "is_single_quarter, is_annual, has_balance_sheet, source_file, loaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(company_symbol, filing_type, context_id, COALESCE(period_end, ''), COALESCE(instant, '')) "
        "DO UPDATE SET period_start=excluded.period_start, is_single_quarter=excluded.is_single_quarter, "
        "is_annual=excluded.is_annual, has_balance_sheet=excluded.has_balance_sheet, "
        "source_file=excluded.source_file, loaded_at=excluded.loaded_at",
        (symbol, filing_type, context_id, period_start, period_end, instant,
         int(is_sq), int(is_ann), int(has_bs), source_file, datetime.now().isoformat()),
    )
    row = conn.execute(
        "SELECT id FROM filings WHERE company_symbol=? AND filing_type=? AND context_id=? "
        "AND (period_end IS ? OR period_end=?) AND (instant IS ? OR instant=?)",
        (symbol, filing_type, context_id, period_end, period_end, instant, instant),
    ).fetchone()
    return row["id"]

_META_KEYS = {"context_id", "period_start", "period_end", "instant",
              "_missing_fields", "_validation", "_needs_review"}

def load_facts_for_filing(conn, filing_id: int, record: dict):
    for key, value in record.items():
        if key in _META_KEYS or value is None:
            continue
        if not isinstance(value, (int, float)):
            continue  # skip non-numeric (shouldn't occur in canonical records, but stay defensive)
        conn.execute(
            "INSERT INTO financial_facts (filing_id, field_name, value) VALUES (?, ?, ?) "
            "ON CONFLICT(filing_id, field_name) DO UPDATE SET value=excluded.value",
            (filing_id, key, float(value)),
        )

_UNIT_MAP = {
    "growth_note": None, 
}

def _infer_unit(metric_name: str) -> str | None:
    if metric_name.endswith("_pct"):
        return "pct"
    if metric_name in ("interest_coverage_ratio", "current_ratio", "debt_to_equity", "asset_turnover",
                        "cash_ratio", "net_debt_to_operating_ebit", "pe_ratio", "pb_ratio", "ev_to_sales"):
        return "x"
    if metric_name in ("ebit", "operating_ebit", "net_debt", "enterprise_value", "ttm_ebit", "ttm_revenue",
                        "total_dividends_paid", "dividend_per_share", "book_value_per_share", "ttm_eps", "latest_close"):
        return "currency"
    if metric_name == "shares_outstanding":
        return "count"
    if metric_name == "operating_leverage_signal":
        return "pp"
    return None

def load_metrics_for_filing(conn, filing_id: int, ratios: dict):
    for metric_name, value in ratios.items():
        if value is None or not isinstance(value, (int, float)):
            continue
        conn.execute(
            "INSERT INTO financial_metrics (filing_id, metric_name, value, unit) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(filing_id, metric_name) DO UPDATE SET value=excluded.value, unit=excluded.unit",
            (filing_id, metric_name, float(value), _infer_unit(metric_name)),
        )

def load_canonical_facts(conn, company_filter: str | None = None):
    """data_extraction's canonical JSONs -> companies + filings + financial_facts."""
    # NOT [A-Z]+ -- real NSE symbols include "-" (BAJAJ-AUTO) and "&"
    # (M&M); the old [A-Z]-only pattern silently skipped both companies
    # entirely (zero facts loaded, no error) on every run. Found live
    # once the pipeline actually covered all 50 companies instead of the
    # original 6, none of which needed the wider character class -- see
    # SESSION_ADDENDUM_6.md.
    pattern = re.compile(r"^(.+)_(consolidated|standalone)_.+_canonical\.json$")
    count_filings = 0
    for path in sorted(EXTRACTED_DIR.glob("*_canonical.json")):
        m = pattern.match(path.name)
        if not m:
            continue
        symbol, filing_type = m.group(1), m.group(2)
        if company_filter and symbol != company_filter:
            continue

        upsert_company(conn, symbol)
        records = json.loads(path.read_text())
        for record in records:
            filing_id = upsert_filing(conn, symbol, filing_type, record, path.name)
            load_facts_for_filing(conn, filing_id, record)
            count_filings += 1
    print(f"[load_data] Loaded facts for {count_filings} filing period(s) from data_extraction")

def load_ratios(conn, company_filter: str | None = None):
    """data_analysis's *_combined_ratios.json -> financial_metrics, matched
    to the SAME filing rows created by load_canonical_facts (by company +
    filing_type + context_id + period_end + instant)."""
    # See load_canonical_facts()'s comment above -- same [A-Z]-only bug.
    pattern = re.compile(r"^(.+)_(consolidated|standalone)_combined_ratios\.json$")
    count_metrics = 0
    for path in sorted(ANALYSIS_DIR.glob("*_combined_ratios.json")):
        m = pattern.match(path.name)
        if not m:
            continue
        symbol, filing_type = m.group(1), m.group(2)
        if company_filter and symbol != company_filter:
            continue

        data = json.loads(path.read_text())
        for period in data.get("periods", []):
            row = conn.execute(
                "SELECT id FROM filings WHERE company_symbol=? AND filing_type=? AND context_id=? "
                "AND (period_end IS ? OR period_end=?) AND (instant IS ? OR instant=?)",
                (symbol, filing_type, period["context_id"], period.get("period_end"), period.get("period_end"),
                 period.get("instant"), period.get("instant")),
            ).fetchone()
            if row is None:
                print(f"  [load_ratios] WARNING: no matching filing for {symbol} {filing_type} "
                      f"{period['context_id']} — run load_canonical_facts first / re-extract.")
                continue
            load_metrics_for_filing(conn, row["id"], period.get("ratios", {}))
            count_metrics += 1
    print(f"[load_data] Loaded ratios for {count_metrics} filing period(s) from data_analysis")

def load_valuation(conn, company_filter: str | None = None):
    """data_analysis's *_valuation.json / *_pb.json -> a synthetic 'TTM'
    filing row per company+filing_type (these are trailing-twelve-month
    figures, not tied to one specific quarter's context)."""
    count = 0
    for path in sorted(ANALYSIS_DIR.glob("*_valuation.json")):
        # See load_canonical_facts()'s comment above -- same [A-Z]-only bug.
        m = re.match(r"^(.+)_(consolidated|standalone)_valuation\.json$", path.name)
        if not m:
            continue
        symbol, filing_type = m.group(1), m.group(2)
        if company_filter and symbol != company_filter:
            continue
        data = json.loads(path.read_text())
        upsert_company(conn, symbol)
        synthetic = {"context_id": "TTM", "period_start": None,
                     "period_end": data.get("price_date"), "instant": None}
        filing_id = upsert_filing(conn, symbol, filing_type, synthetic, path.name)
        metrics = {k: v for k, v in data.items()
                   if k in ("latest_close", "ttm_eps", "pe_ratio") and isinstance(v, (int, float))}
        load_metrics_for_filing(conn, filing_id, metrics)

        pb_path = path.parent / path.name.replace("_valuation.json", "_pb.json")
        if pb_path.exists():
            pb_data = json.loads(pb_path.read_text())
            pb_metrics = {k: v for k, v in pb_data.items()
                          if k in ("book_value_per_share", "pb_ratio") and isinstance(v, (int, float))}
            load_metrics_for_filing(conn, filing_id, pb_metrics)

        ey_path = path.parent / path.name.replace("_valuation.json", "_earnings_yield.json")
        if ey_path.exists():
            ey_data = json.loads(ey_path.read_text())
            ey_metrics = {k: v for k, v in ey_data.items()
                          if k in ("enterprise_value", "ttm_ebit", "earnings_yield_pct") and isinstance(v, (int, float))}
            load_metrics_for_filing(conn, filing_id, ey_metrics)

        evs_path = path.parent / path.name.replace("_valuation.json", "_ev_to_sales.json")
        if evs_path.exists():
            evs_data = json.loads(evs_path.read_text())
            evs_metrics = {k: v for k, v in evs_data.items()
                          if k in ("ttm_revenue", "ev_to_sales") and isinstance(v, (int, float))}
            load_metrics_for_filing(conn, filing_id, evs_metrics)

        dy_path = path.parent / path.name.replace("_valuation.json", "_dividend_yield.json")
        if dy_path.exists():
            dy_data = json.loads(dy_path.read_text())
            dy_metrics = {k: v for k, v in dy_data.items()
                          if k in ("total_dividends_paid", "dividend_per_share", "dividend_yield_pct") and isinstance(v, (int, float))}
            load_metrics_for_filing(conn, filing_id, dy_metrics)
        count += 1
    print(f"[load_data] Loaded valuation for {count} company/filing-type combination(s)")

def load_prices(conn, company_filter: str | None = None):
    """data_extraction's price CSVs -> share_prices."""
    count = 0
    for path in sorted(PRICES_DIR.glob("*_prices.csv")):
        symbol = path.name.replace("_prices.csv", "")
        if company_filter and symbol != company_filter:
            continue
        upsert_company(conn, symbol)
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_date = row.get("DATE", "")
                day = raw_date[:10] if raw_date else None
                if not day:
                    continue

                def num(field):
                    try:
                        return float(row[field])
                    except (KeyError, ValueError):
                        return None

                conn.execute(
                    "INSERT INTO share_prices (company_symbol, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(company_symbol, date) DO UPDATE SET "
                    "open=excluded.open, high=excluded.high, low=excluded.low, "
                    "close=excluded.close, volume=excluded.volume",
                    (symbol, day, num("OPEN"), num("HIGH"), num("LOW"), num("CLOSE"), num("VOLUME")),
                )
                count += 1
    print(f"[load_data] Loaded {count} price row(s)")

def load_all(company_filter: str | None = None):
    init_db()
    with get_connection() as conn:
        load_canonical_facts(conn, company_filter)
        load_ratios(conn, company_filter)
        load_valuation(conn, company_filter)
        load_prices(conn, company_filter)
    print("[load_data] Done.")

if __name__ == "__main__":
    company = sys.argv[1] if len(sys.argv) > 1 else None
    load_all(company)