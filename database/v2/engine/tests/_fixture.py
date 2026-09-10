"""Shared in-memory fixture: one company, two annual periods + two quarters,
with hand-chosen round numbers so ratio expectations are obvious.
"""
from __future__ import annotations

from datetime import date

from database.v2.models import Basis, Company, FinancialFact, StatementType

PL = StatementType.PROFIT_AND_LOSS
BS = StatementType.BALANCE_SHEET
CF = StatementType.CASH_FLOW
CONS = Basis.CONSOLIDATED


def _pl(cid, metric, value, fy, q, ps, pe, *, annual=False):
    return FinancialFact(
        company_id=cid, metric=metric, value=value, unit="INR", statement_type=PL, basis=CONS,
        period_start=ps, period_end=pe, financial_year=fy, quarter=q, is_annual=annual,
    )


def _bs(cid, metric, value, fy, pe):
    return FinancialFact(
        company_id=cid, metric=metric, value=value, unit="INR", statement_type=BS, basis=CONS,
        period_start=None, period_end=pe, financial_year=fy, quarter=None,
        is_annual=False, is_point_in_time=True,
    )


def seed(repos) -> int:
    cid = repos.companies.upsert(Company(name="Testco", ticker="TEST")).company_id

    facts: list[FinancialFact] = []
    # --- FY2025 annual: revenue 1000, net_profit 100, expenses 850, pbt 150 ---
    for m, v in [("revenue", 1000.0), ("net_profit", 100.0), ("total_expenses", 850.0),
                 ("pbt", 150.0), ("pbt_before_exceptional", 150.0), ("finance_costs", 10.0),
                 ("depreciation", 40.0), ("other_income", 0.0), ("tax_expense", 50.0),
                 ("employee_expense", 500.0), ("other_expenses", 310.0)]:
        facts.append(_pl(cid, m, v, 2025, None, date(2024, 4, 1), date(2025, 3, 31), annual=True))
    # BS as of 2025-03-31: equity 500, assets 2000, current_liab 300, current_assets 600,
    # borrowings_noncurrent 200, cash 150
    for m, v in [("total_equity", 500.0), ("total_assets", 2000.0), ("current_liabilities", 300.0),
                 ("current_assets", 600.0), ("borrowings_noncurrent", 200.0), ("cash_and_equivalents", 150.0),
                 ("total_liabilities", 1500.0)]:
        facts.append(_bs(cid, m, v, 2025, date(2025, 3, 31)))

    # --- FY2026 annual: revenue 1200 (+20%), net_profit 150, expenses 990 ---
    for m, v in [("revenue", 1200.0), ("net_profit", 150.0), ("total_expenses", 990.0),
                 ("pbt", 210.0), ("pbt_before_exceptional", 210.0), ("finance_costs", 12.0),
                 ("depreciation", 48.0), ("other_income", 0.0), ("tax_expense", 60.0),
                 ("employee_expense", 600.0), ("other_expenses", 342.0)]:
        facts.append(_pl(cid, m, v, 2026, None, date(2025, 4, 1), date(2026, 3, 31), annual=True))
    for m, v in [("total_equity", 600.0), ("total_assets", 2400.0), ("current_liabilities", 360.0),
                 ("current_assets", 720.0), ("borrowings_noncurrent", 240.0), ("cash_and_equivalents", 180.0),
                 ("total_liabilities", 1800.0)]:
        facts.append(_bs(cid, m, v, 2026, date(2026, 3, 31)))

    # --- two quarters of FY2026 for QoQ: Q1 revenue 280, Q2 revenue 300 ---
    facts.append(_pl(cid, "revenue", 280.0, 2026, 1, date(2025, 4, 1), date(2025, 6, 30)))
    facts.append(_pl(cid, "net_profit", 34.0, 2026, 1, date(2025, 4, 1), date(2025, 6, 30)))
    facts.append(_pl(cid, "revenue", 300.0, 2026, 2, date(2025, 7, 1), date(2025, 9, 30)))
    facts.append(_pl(cid, "net_profit", 36.0, 2026, 2, date(2025, 7, 1), date(2025, 9, 30)))

    repos.facts.add_many(facts)
    repos.commit()
    return cid
