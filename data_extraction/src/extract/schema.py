
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

    # Equity/capital
    "paid_up_equity_capital": "in-capmkt:PaidUpValueOfEquityShareCapital",
    "face_value_per_share": "in-capmkt:FaceValueOfEquityShareCapital",
    "debt_equity_ratio_reported": "in-capmkt:DebtEquityRatio",
    "total_assets": None,
    "total_liabilities": None,
    "total_equity": None,
}

# Matches "OneD", "TwoD", "ThreeD", "OneI", "TwoI", etc. — the primary
# whole-company contexts. Rejects anything with extra suffix text
# (segment/note-breakdown contexts like "OneReportable1D", "OneExpenses2D").
PRIMARY_CONTEXT_PATTERN = re.compile(r"^(One|Two|Three|Four|Five|Six)[DI]$")


def is_primary_context(context_id: str) -> bool:
    return bool(PRIMARY_CONTEXT_PATTERN.match(context_id or ""))


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
        if not is_primary_context(ctx_id): # type: ignore
            continue
        tag = fact.get("line_item_tag")
        canonical_name = tag_to_canonical.get(tag)
        if canonical_name is None:
            continue  

        value = to_number(fact.get("value"))  # type: ignore
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
        records.append(record)

    # Sort by period_end (or instant) so the current quarter is first —
    # makes the output easier to scan.
    records.sort(key=lambda r: r.get("period_end") or r.get("instant") or "", reverse=True)
    return records


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.extract.schema <path-to-{symbol}_facts_raw.json>")
        print("  (the file xbrl_lite_parser.py already saves to data/extracted/)")
        sys.exit(1)

    raw_path = Path(sys.argv[1])
    facts = json.loads(raw_path.read_text())
    canonical = map_facts_to_canonical(facts)

    out_path = raw_path.parent / raw_path.name.replace("_facts_raw.json", "_canonical.json")
    out_path.write_text(json.dumps(canonical, indent=2, default=str))

    print(f"Mapped {len(facts)} raw facts into {len(canonical)} period record(s).")
    print(f"Saved to {out_path}\n")
    for r in canonical:
        label = r.get("period_end") or r.get("instant")
        print(f"--- context={r['context_id']}  period={label} ---")
        for k, v in r.items():
            if k in ("context_id", "period_start", "period_end", "instant", "_missing_fields"):
                continue
            print(f"  {k:30s} = {v}")
        if r["_missing_fields"]:
            print(f"  (not found in this context: {', '.join(r['_missing_fields'])})")
        print()
