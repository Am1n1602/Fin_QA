"""
Phase 3 — validation. Deterministic checks, no LLM involved. Run these on
anything extracted (XBRL facts or PDF tables) before trusting it. A failed
check should route the record to manual review, not silently pass through.
"""


def to_number(raw: str) -> float | None:
    """Parse Indian-formatted numbers: '59,553.00', '(1,234.5)' for
    negatives, strip currency symbols/footnote markers."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s in ("-", "—", "NA", "N/A"):
        return None
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").replace("₹", "").strip()
    # strip trailing footnote markers like "1,234.5*" or "1,234.5^1"
    s = "".join(c for c in s if c.isdigit() or c == "." or c == "-")
    try:
        val = float(s)
        return -val if negative else val
    except ValueError:
        return None


def check_balance_sheet_balances(total_assets: float, total_liabilities: float,
                                   total_equity: float, tolerance: float = 1.0) -> bool:
    """Assets = Liabilities + Equity, within a small rounding tolerance
    (filings round to the nearest lakh/crore, so exact equality is rare)."""
    if None in (total_assets, total_liabilities, total_equity):
        return False
    return abs(total_assets - (total_liabilities + total_equity)) <= tolerance


def check_pnl_arithmetic(revenue: float, total_expenses: float, pbt: float,
                          tolerance: float = 1.0) -> bool:
    """Revenue - Total Expenses = Profit Before Tax (before exceptional
    items — check your specific filing's line structure, some companies
    report exceptional items as a separate line above PBT)."""
    if None in (revenue, total_expenses, pbt):
        return False
    return abs((revenue - total_expenses) - pbt) <= tolerance


def check_period_consistency(current_period_value: float, prior_period_comparative: float,
                              tolerance_pct: float = 0.5) -> bool:
    """Cross-check: does this quarter's 'previous period' comparative
    column match what you actually extracted as the current-period value
    from THAT prior quarter's filing? A mismatch usually means a
    misaligned column in table extraction, not a real restatement —
    though restatements do happen, so a genuine mismatch is worth a
    manual look either way."""
    if None in (current_period_value, prior_period_comparative) or prior_period_comparative == 0:
        return False
    pct_diff = abs(current_period_value - prior_period_comparative) / abs(prior_period_comparative) * 100
    return pct_diff <= tolerance_pct


def validate_extracted_record(record: dict) -> dict:
    """
    Run all applicable checks on one normalized filing record (a dict with
    keys like total_assets, total_liabilities, total_equity, revenue,
    total_expenses, pbt — whatever you've mapped from XBRL/PDF extraction).
    Returns the record with a `_validation` block attached; does not raise,
    so you can batch-process and filter failures afterward.
    """
    results = {}
    if all(k in record for k in ("total_assets", "total_liabilities", "total_equity")):
        results["balance_sheet_balances"] = check_balance_sheet_balances(
            record["total_assets"], record["total_liabilities"], record["total_equity"]
        )
    if all(k in record for k in ("revenue", "total_expenses", "pbt")):
        results["pnl_arithmetic_ok"] = check_pnl_arithmetic(
            record["revenue"], record["total_expenses"], record["pbt"]
        )
    record["_validation"] = results
    record["_needs_review"] = (len(results) > 0) and not all(results.values())
    return record
