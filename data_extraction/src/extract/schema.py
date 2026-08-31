import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from src.extract.validate import to_number

TAG_MAP = {
    # P&L
    "revenue": "in-capmkt:RevenueFromOperations",
    "other_income": "in-capmkt:OtherIncome",
    "total_income": "in-capmkt:Income",
    "employee_expense": "in-capmkt:EmployeeBenefitExpense",
    "depreciation": "in-capmkt:DepreciationDepletionAndAmortisationExpense",
    "other_expenses": "in-capmkt:OtherExpenses",
    "finance_costs": "in-capmkt:FinanceCosts",
    "total_expenses": "in-capmkt:Expenses",
    "pbt_before_exceptional": "in-capmkt:ProfitBeforeExceptionalItemsAndTax",
    "exceptional_items": "in-capmkt:ExceptionalItemsBeforeTax",
    "pbt": "in-capmkt:ProfitBeforeTax",
    "current_tax": "in-capmkt:CurrentTax",
    "deferred_tax": "in-capmkt:DeferredTax",
    "tax_expense": "in-capmkt:TaxExpense",
    "pat_continuing_ops": "in-capmkt:ProfitLossForPeriodFromContinuingOperations",
    "net_profit": "in-capmkt:ProfitLossForPeriod",
    "oci": "in-capmkt:OtherComprehensiveIncomeNetOfTaxes",
    "total_comprehensive_income": "in-capmkt:ComprehensiveIncomeForThePeriod",
    "net_profit_owners": "in-capmkt:ProfitOrLossAttributableToOwnersOfParent",
    "net_profit_nci": "in-capmkt:ProfitOrLossAttributableToNonControllingInterests",
    "eps_basic": "in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
    "eps_diluted": "in-capmkt:DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",

    # Equity/capital
    "paid_up_equity_capital": "in-capmkt:PaidUpValueOfEquityShareCapital",
    "face_value_per_share": "in-capmkt:FaceValueOfEquityShareCapital",
    "debt_equity_ratio_reported": "in-capmkt:DebtEquityRatio",

    # Balance sheet
    "total_assets": "in-capmkt:Assets",
    "total_liabilities": "in-capmkt:Liabilities",
    "total_equity": "in-capmkt:Equity",
    "current_assets": "in-capmkt:CurrentAssets",
    "noncurrent_assets": "in-capmkt:NoncurrentAssets",
    "current_liabilities": "in-capmkt:CurrentLiabilities",
    "noncurrent_liabilities": "in-capmkt:NoncurrentLiabilities",
    "borrowings_current": "in-capmkt:BorrowingsCurrent",
    "borrowings_noncurrent": "in-capmkt:BorrowingsNoncurrent",
    "cash_and_equivalents": "in-capmkt:CashAndCashEquivalents",

    "operating_cash_flow": "in-capmkt:CashFlowsFromUsedInOperatingActivities",
    "investing_cash_flow": "in-capmkt:CashFlowsFromUsedInInvestingActivities",
    "financing_cash_flow": "in-capmkt:CashFlowsFromUsedInFinancingActivities",
    "dividends": "in-capmkt:DividendsPaidClassifiedAsFinancingActivities",

    "capex_ppe": "in-capmkt:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "capex_intangibles": "in-capmkt:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
}

# Matches "OneD", "TwoD", "ThreeD", "OneI", "TwoI", etc. — the primary
# whole-company contexts. Also matches "PY_D"/"PY_I" (prior-year contexts
# seen in annual filings — e.g. "PY_I" for the prior year-end balance
# sheet snapshot). Rejects anything with extra suffix text (segment/note-
# breakdown contexts like "OneReportable1D", "OneExpenses2D").
PRIMARY_CONTEXT_PATTERN = re.compile(r"^(One|Two|Three|Four|Five|Six)[DI]$|^PY_[DI]$")


def is_primary_context(context_id: str) -> bool:
    return bool(PRIMARY_CONTEXT_PATTERN.match(context_id or ""))


def validate_canonical_record(record: dict, tolerance: float = 1.0) -> dict:
    """P&L arithmetic checks specific to this schema's field names.
    Attaches a `_validation` dict; never raises, so batch runs don't stop
    on a bad quarter — flag it and move on."""
    checks = {}

    if all(record.get(k) is not None for k in ("total_income", "total_expenses", "pbt_before_exceptional")):
        checks["income_minus_expenses_eq_pbt_before_exceptional"] = (
            abs((record["total_income"] - record["total_expenses"]) - record["pbt_before_exceptional"]) <= tolerance
        )

    if all(record.get(k) is not None for k in ("pbt_before_exceptional", "exceptional_items", "pbt")):
        checks["pbt_before_exceptional_plus_exceptional_eq_pbt"] = (
            abs((record["pbt_before_exceptional"] + record["exceptional_items"]) - record["pbt"]) <= tolerance
        )

    if all(record.get(k) is not None for k in ("current_tax", "deferred_tax", "tax_expense")):
        checks["current_plus_deferred_tax_eq_tax_expense"] = (
            abs((record["current_tax"] + record["deferred_tax"]) - record["tax_expense"]) <= tolerance
        )

    if all(record.get(k) is not None for k in ("pbt", "tax_expense", "net_profit")):
        checks["pbt_minus_tax_eq_net_profit"] = (
            abs((record["pbt"] - record["tax_expense"]) - record["net_profit"]) <= tolerance
        )

    if all(record.get(k) is not None for k in ("net_profit", "oci", "total_comprehensive_income")):
        checks["net_profit_plus_oci_eq_total_comprehensive_income"] = (
            abs((record["net_profit"] + record["oci"]) - record["total_comprehensive_income"]) <= tolerance
        )

    # Balance sheet checks — only run once these fields exist on a record
    # (post-merge with an instant context; see merge_periods()).
    if all(record.get(k) is not None for k in ("total_assets", "total_liabilities", "total_equity")):
        checks["assets_eq_liabilities_plus_equity"] = (
            abs(record["total_assets"] - (record["total_liabilities"] + record["total_equity"])) <= tolerance
        )

    if all(record.get(k) is not None for k in ("current_assets", "noncurrent_assets", "total_assets")):
        checks["current_plus_noncurrent_assets_eq_total_assets"] = (
            abs((record["current_assets"] + record["noncurrent_assets"]) - record["total_assets"]) <= tolerance
        )

    if all(record.get(k) is not None for k in ("current_liabilities", "noncurrent_liabilities", "total_liabilities")):
        checks["current_plus_noncurrent_liabilities_eq_total_liabilities"] = (
            abs((record["current_liabilities"] + record["noncurrent_liabilities"]) - record["total_liabilities"]) <= tolerance
        )

    record["_validation"] = checks
    record["_needs_review"] = len(checks) > 0 and not all(checks.values())
    return record


def map_facts_to_canonical(facts: list[dict]) -> list[dict]:
    """
    Takes the raw fact list (as produced by xbrl_lite_parser) and returns
    one canonical record PER PRIMARY CONTEXT (i.e. per reporting period —
    current quarter, comparative quarter, YTD, etc., however many the
    filing includes). Facts under non-primary (segment/note) contexts are
    dropped here — reintroduce them separately later if you specifically
    want segment-level analysis.
    """
    # Reverse lookup: raw tag -> canonical name (skip unmapped/None entries)
    tag_to_canonical = {v: k for k, v in TAG_MAP.items() if v is not None}

    by_context = defaultdict(dict)
    context_period_info = {}

    for fact in facts:
        ctx_id = fact.get("context_id")
        if not is_primary_context(ctx_id):
            continue
        tag = fact.get("line_item_tag")
        canonical_name = tag_to_canonical.get(tag)
        if canonical_name is None:
            continue  # not a field we're tracking

        value = to_number(fact.get("value"))
        if value is not None and fact.get("sign") == "-":
            value = -value

        by_context[ctx_id][canonical_name] = value
        context_period_info[ctx_id] = {
            "context_id": ctx_id,
            "period_start": fact.get("period_start"),
            "period_end": fact.get("period_end"),
            "instant": fact.get("instant"),
        }

    records = []
    for ctx_id, fields in by_context.items():
        record = dict(context_period_info[ctx_id])
        record.update(fields)
        # Note which canonical fields were expected but not found in this
        # context — makes gaps visible instead of silently missing.
        record["_missing_fields"] = [
            k for k in TAG_MAP if TAG_MAP[k] is not None and k not in fields
        ]
        record = validate_canonical_record(record)
        records.append(record)

    # Sort by period_end (or instant) so the current quarter is first —
    # makes the output easier to scan.
    records.sort(key=lambda r: r.get("period_end") or r.get("instant") or "", reverse=True)
    return records


def merge_periods(records: list[dict]) -> list[dict]:
    duration_records = [r for r in records if r.get("period_end") is not None]
    instant_records = [r for r in records if r.get("instant") is not None]

    instant_by_date = defaultdict(list)
    for r in instant_records:
        instant_by_date[r["instant"]].append(r)

    used_instant_context_ids = set()
    merged = []
    for d in duration_records:
        matches = instant_by_date.get(d.get("period_end"), [])
        if not matches:
            merged.append(d)
            continue

        inst = matches[0]  # normally exactly one primary instant context per date
        used_instant_context_ids.add(inst["context_id"])

        combined = dict(d)
        combined["context_id"] = f"{d['context_id']}+{inst['context_id']}"
        skip_keys = {"context_id", "period_start", "period_end", "instant", "_missing_fields", "_validation", "_needs_review"}
        for k, v in inst.items():
            if k in skip_keys:
                continue
            combined[k] = v

        combined["_missing_fields"] = [
            k for k in TAG_MAP if TAG_MAP[k] is not None and combined.get(k) is None
        ]
        combined = validate_canonical_record(combined)
        merged.append(combined)

    for inst in instant_records:
        if inst["context_id"] not in used_instant_context_ids:
            merged.append(inst)

    merged.sort(key=lambda r: r.get("period_end") or r.get("instant") or "", reverse=True)
    return merged


def map_and_save(raw_json_path) -> tuple[Path, int]:
    """Load a *_facts_raw.json, map it to canonical schema, save
    *_canonical.json alongside it. Returns (output_path, period_count) —
    used by both the CLI below and run_extraction.py's batch runner."""
    raw_json_path = Path(raw_json_path)
    facts = json.loads(raw_json_path.read_text())
    canonical = map_facts_to_canonical(facts)
    canonical = merge_periods(canonical)
    out_path = raw_json_path.parent / raw_json_path.name.replace("_facts_raw.json", "_canonical.json")
    out_path.write_text(json.dumps(canonical, indent=2, default=str))
    return out_path, len(canonical)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.extract.schema <path-to-{symbol}_facts_raw.json>")
        print("  (the file xbrl_lite_parser.py already saves to data/extracted/)")
        sys.exit(1)

    raw_path = Path(sys.argv[1])
    out_path, n_periods = map_and_save(raw_path)
    facts = json.loads(raw_path.read_text())
    canonical = json.loads(out_path.read_text())

    print(f"Mapped {len(facts)} raw facts into {n_periods} period record(s).")
    print(f"Saved to {out_path}\n")
    for r in canonical:
        label = f"{r.get('period_start')} to {r.get('period_end')}" if r.get("period_start") else (r.get("period_end") or r.get("instant"))
        print(f"--- context={r['context_id']}  period={label} ---")
        for k, v in r.items():
            if k in ("context_id", "period_start", "period_end", "instant", "_missing_fields", "_validation", "_needs_review"):
                continue
            print(f"  {k:30s} = {v}")
        if r["_missing_fields"]:
            print(f"  (not found in this context: {', '.join(r['_missing_fields'])})")
        if r["_needs_review"]:
            failed = [k for k, v in r["_validation"].items() if not v]
            print(f"  ⚠ VALIDATION FAILED: {', '.join(failed)}")
        else:
            print(f"  ✓ all arithmetic checks passed")
        print()