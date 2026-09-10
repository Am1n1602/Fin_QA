"""Financial ratios. Formulas ported from data_analysis/src/analysis/ratios.py.

Each ratio is a RatioSpec so the engine can report unit + formula + the exact inputs
used. `value is None` whenever a required input is missing -- never 0, never a proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from finqa_v2.engine import derive

Rec = Mapping[str, float]


def _div(num, den, *, pct: bool):
    if num is None or den in (None, 0):
        return None
    r = num / den
    return r * 100 if pct else r


def top_line(r: Rec):
    """Revenue, falling back to total_income for banks / insurers that file no 'revenue'
    line (IRDAI / RBI statement formats). `total_income` there is premium + investment
    income (insurers) or interest + other income (banks)."""
    v = r.get("revenue")
    return v if v is not None else r.get("total_income")


@dataclass(frozen=True, slots=True)
class RatioSpec:
    name: str
    unit: str                      # 'pct' | 'x'
    inputs: tuple[str, ...]        # canonical metrics / derived names referenced
    formula: str
    compute: Callable[[Rec], float | None]


def _ebitda_margin(r: Rec):
    e = derive.ebitda(r)
    return _div(e, r.get("revenue"), pct=True)


def _ebit_margin(r: Rec):
    return _div(derive.ebit(r), r.get("revenue"), pct=True)


def _roce(r: Rec):
    ta, cl = r.get("total_assets"), r.get("current_liabilities")
    e = derive.ebit(r)
    if None in (ta, cl) or e is None:
        return None
    return _div(e, ta - cl, pct=True)


def _interest_coverage(r: Rec):
    fc = r.get("finance_costs") or 0
    if not fc:
        return None
    return _div(r.get("pbt_before_exceptional"), fc, pct=False)


SPECS: dict[str, RatioSpec] = {
    "roe": RatioSpec("roe", "pct", ("net_profit", "total_equity"),
                     "net_profit / total_equity * 100",
                     lambda r: _div(r.get("net_profit"), r.get("total_equity"), pct=True)),
    "roa": RatioSpec("roa", "pct", ("net_profit", "total_assets"),
                     "net_profit / total_assets * 100",
                     lambda r: _div(r.get("net_profit"), r.get("total_assets"), pct=True)),
    "roce": RatioSpec("roce", "pct", ("ebit", "total_assets", "current_liabilities"),
                      "ebit / (total_assets - current_liabilities) * 100", _roce),
    "ebitda_margin": RatioSpec("ebitda_margin", "pct",
                               ("pbt_before_exceptional", "depreciation", "finance_costs", "other_income", "revenue"),
                               "(pbt_before_exceptional + depreciation + finance_costs - other_income) / revenue * 100",
                               _ebitda_margin),
    "ebit_margin": RatioSpec("ebit_margin", "pct", ("pbt_before_exceptional", "finance_costs", "revenue"),
                             "(pbt_before_exceptional + finance_costs) / revenue * 100", _ebit_margin),
    "net_profit_margin": RatioSpec("net_profit_margin", "pct", ("net_profit", "revenue"),
                                   "net_profit / revenue * 100",
                                   lambda r: _div(r.get("net_profit"), top_line(r), pct=True)),
    "pbt_margin": RatioSpec("pbt_margin", "pct", ("pbt", "revenue"),
                            "pbt / revenue * 100",
                            lambda r: _div(r.get("pbt"), r.get("revenue"), pct=True)),
    "debt_to_equity": RatioSpec("debt_to_equity", "x", ("total_debt", "total_equity"),
                                "total_debt / total_equity",
                                lambda r: None if r.get("total_equity") is None
                                else _div(derive.total_debt(r), r.get("total_equity"), pct=False)),
    "interest_coverage": RatioSpec("interest_coverage", "x", ("pbt_before_exceptional", "finance_costs"),
                                   "pbt_before_exceptional / finance_costs", _interest_coverage),
    "current_ratio": RatioSpec("current_ratio", "x", ("current_assets", "current_liabilities"),
                               "current_assets / current_liabilities",
                               lambda r: _div(r.get("current_assets"), r.get("current_liabilities"), pct=False)),
    "asset_turnover": RatioSpec("asset_turnover", "x", ("revenue", "total_assets"),
                                "revenue / total_assets",
                                lambda r: _div(top_line(r), r.get("total_assets"), pct=False)),
    "effective_tax_rate": RatioSpec("effective_tax_rate", "pct", ("tax_expense", "pbt"),
                                    "tax_expense / pbt * 100",
                                    lambda r: _div(r.get("tax_expense"), r.get("pbt"), pct=True)),
    "cash_ratio": RatioSpec("cash_ratio", "x", ("cash_and_equivalents", "current_liabilities"),
                            "cash_and_equivalents / current_liabilities",
                            lambda r: _div(r.get("cash_and_equivalents"), r.get("current_liabilities"), pct=False)),
    "equity_to_assets": RatioSpec("equity_to_assets", "pct", ("total_equity", "total_assets"),
                                  "total_equity / total_assets * 100",
                                  lambda r: _div(r.get("total_equity"), r.get("total_assets"), pct=True)),
    "payout_ratio": RatioSpec("payout_ratio", "pct", ("dividends", "net_profit"),
                              "dividends / net_profit * 100",
                              lambda r: _div(r.get("dividends"), r.get("net_profit"), pct=True)),
    # --- bank ---
    "net_interest_margin": RatioSpec("net_interest_margin", "pct",
                                     ("bank_interest_earned", "bank_interest_expended", "total_assets"),
                                     "(bank_interest_earned - bank_interest_expended) / total_assets * 100",
                                     lambda r: _div(
                                         None if None in (r.get("bank_interest_earned"), r.get("bank_interest_expended"))
                                         else r["bank_interest_earned"] - r["bank_interest_expended"],
                                         r.get("total_assets"), pct=True)),
    "credit_cost": RatioSpec("credit_cost", "pct", ("bank_provisions", "advances"),
                             "bank_provisions / advances * 100",
                             lambda r: _div(r.get("bank_provisions"), r.get("advances"), pct=True)),
}

ALIASES = {
    "return_on_equity": "roe", "return_on_assets": "roa", "return_on_capital_employed": "roce",
    "roce_pct": "roce", "roe_pct": "roe", "roa_pct": "roa",
    "npm": "net_profit_margin", "net_margin": "net_profit_margin", "npm_pct": "net_profit_margin",
    "de": "debt_to_equity", "d/e": "debt_to_equity", "leverage": "debt_to_equity",
    "ebitda_margin_pct": "ebitda_margin", "ebit_margin_pct": "ebit_margin",
    "interest_coverage_ratio": "interest_coverage", "nim": "net_interest_margin",
}


def resolve(name: str) -> str | None:
    key = name.strip().lower()
    if key in SPECS:
        return key
    return ALIASES.get(key)


def get_spec(name: str) -> RatioSpec | None:
    key = resolve(name)
    return SPECS.get(key) if key else None


def known() -> list[str]:
    return sorted(SPECS)
