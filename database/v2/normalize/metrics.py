"""Canonical metric registry: name -> unit / statement_type / point-in-time.

Ports the canonical field set from data_extraction/src/extract/schema.py's TAG_MAP.
This is where v2 owns the canonical mapping definition (roadmap section 10).
"""
from __future__ import annotations

from dataclasses import dataclass

from database.v2.models import StatementType

PL = StatementType.PROFIT_AND_LOSS
BS = StatementType.BALANCE_SHEET
CF = StatementType.CASH_FLOW
OTHER = StatementType.OTHER

# unit vocabulary used here: 'INR' | 'per_share' | 'x' | 'shares'


@dataclass(frozen=True, slots=True)
class MetricSpec:
    unit: str
    statement_type: StatementType
    is_point_in_time: bool          # True -> balance-sheet snapshot (no period_start/quarter)
    label: str


def _pl(label: str, unit: str = "INR") -> MetricSpec:
    return MetricSpec(unit, PL, False, label)


def _bs(label: str, unit: str = "INR") -> MetricSpec:
    return MetricSpec(unit, BS, True, label)


def _cf(label: str, unit: str = "INR") -> MetricSpec:
    return MetricSpec(unit, CF, False, label)


REGISTRY: dict[str, MetricSpec] = {
    # --- P&L (duration) ---
    "revenue": _pl("Revenue from operations"),
    "other_income": _pl("Other income"),
    "total_income": _pl("Total income"),
    "employee_expense": _pl("Employee benefit expense"),
    "depreciation": _pl("Depreciation & amortisation"),
    "other_expenses": _pl("Other expenses"),
    "finance_costs": _pl("Finance costs"),
    "total_expenses": _pl("Total expenses"),
    "pbt_before_exceptional": _pl("Profit before exceptional items and tax"),
    "exceptional_items": _pl("Exceptional items (before tax)"),
    "pbt": _pl("Profit before tax"),
    "current_tax": _pl("Current tax"),
    "deferred_tax": _pl("Deferred tax"),
    "tax_expense": _pl("Total tax expense"),
    "pat_continuing_ops": _pl("Profit for the period from continuing operations"),
    "net_profit": _pl("Profit for the period"),
    "oci": _pl("Other comprehensive income (net of tax)"),
    "total_comprehensive_income": _pl("Total comprehensive income"),
    "net_profit_owners": _pl("Profit attributable to owners of the parent"),
    "net_profit_nci": _pl("Profit attributable to non-controlling interests"),
    "eps_basic": _pl("Basic EPS", unit="per_share"),
    "eps_diluted": _pl("Diluted EPS", unit="per_share"),

    # --- Equity / capital (balance-sheet-date) ---
    "paid_up_equity_capital": _bs("Paid-up equity share capital"),
    "face_value_per_share": _bs("Face value per share", unit="per_share"),
    "debt_equity_ratio_reported": MetricSpec("x", OTHER, False, "Debt/Equity ratio (as reported)"),

    # --- Balance sheet (instant) ---
    "total_assets": _bs("Total assets"),
    "total_liabilities": _bs("Total liabilities"),
    "total_equity": _bs("Total equity"),
    "current_assets": _bs("Current assets"),
    "noncurrent_assets": _bs("Non-current assets"),
    "current_liabilities": _bs("Current liabilities"),
    "noncurrent_liabilities": _bs("Non-current liabilities"),
    "borrowings_current": _bs("Current borrowings"),
    "borrowings_noncurrent": _bs("Non-current borrowings"),
    "cash_and_equivalents": _bs("Cash and cash equivalents"),
    "debt_securities": _bs("Debt securities"),
    "deposits_debt": _bs("Deposits (debt)"),

    # --- Cash flow (duration) ---
    "operating_cash_flow": _cf("Cash flow from operating activities"),
    "investing_cash_flow": _cf("Cash flow from investing activities"),
    "financing_cash_flow": _cf("Cash flow from financing activities"),
    "dividends": _cf("Dividends paid (financing)"),
    "capex_ppe": _cf("Purchase of property, plant & equipment"),
    "capex_intangibles": _cf("Purchase of intangible assets"),

    # --- Bank-specific P&L (duration) ---
    "bank_interest_earned": _pl("Interest earned (bank)"),
    "bank_interest_expended": _pl("Interest expended (bank)"),
    "bank_operating_profit": _pl("Operating profit before provisions & contingencies (bank)"),
    "bank_provisions": _pl("Provisions other than tax & contingencies (bank)"),
    "bank_employee_cost": _pl("Employee cost (bank)"),
    "bank_other_operating_expenses": _pl("Other operating expenses (bank)"),

    # --- Bank-specific balance sheet (instant) ---
    "advances": _bs("Advances (bank)"),
}


def get(name: str) -> MetricSpec | None:
    return REGISTRY.get(name)


def is_known(name: str) -> bool:
    return name in REGISTRY


def canonical_names() -> list[str]:
    return list(REGISTRY)
