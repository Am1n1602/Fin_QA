"""Hypothesis-testing fixtures: the shared engine seed, plus hand-built decomposition
views for the unit tests that don't need a database.
"""
from __future__ import annotations

from finqa_v2.engine import FinancialEngine
from finqa_v2.engine.tests._fixture import seed as seed_engine
from finqa_v2.hypothesis.decompose import DecompositionView
from finqa_v2.hypothesis.models import MetricChange
from finqa_v2.sqlite import SqliteRepositories


def engine_repos():
    repos = SqliteRepositories(":memory:")
    seed_engine(repos)               # company TEST, FY2025 + FY2026 annual + two quarters
    return FinancialEngine(repos), repos


def decline_view() -> DecompositionView:
    """A profitability DECLINE driven by employee costs outrunning revenue."""
    change = MetricChange(
        ticker="ACME", metric="net_profit", basis="consolidated",
        from_period="FY2025", to_period="FY2026",
        from_value=100.0, to_value=80.0, abs_change=-20.0, pct_change=-20.0,
        evidence_id="ev-change",
    )
    return DecompositionView(
        change=change,
        components={
            "revenue": {"pct": 6.0, "abs": 60.0, "from": 1000.0, "to": 1060.0},
            "employee_expense": {"pct": 18.0, "abs": 90.0, "from": 500.0, "to": 590.0},
            "finance_costs": {"pct": 2.0, "abs": 0.4, "from": 20.0, "to": 20.4},
            "total_expenses": {"pct": 11.0, "abs": 93.0, "from": 850.0, "to": 943.0},
        },
        margin_bridge={"net_margin_change_pp": -2.4, "revenue_effect_pp": 0.3,
                       "expense_effect_pp": -2.7},
        dupont={"net_profit_margin": {"from": 10.0, "to": 7.5, "delta": -2.5},
                "asset_turnover": {"from": 0.5, "to": 0.5, "delta": 0.0},
                "equity_multiplier": {"from": 4.0, "to": 4.0, "delta": 0.0}},
        segments=[{"segment": "Widgets", "abs": 80.0, "pct": 12.0, "share_pct": 133.0},
                  {"segment": "Gadgets", "abs": -20.0, "pct": -8.0, "share_pct": -33.0}],
        evidence={"component_growth:revenue": "ev-rev",
                  "component_growth:employee_expense": "ev-emp",
                  "component_growth:finance_costs": "ev-fin",
                  "component_growth:total_expenses": "ev-tot",
                  "margin_bridge": "ev-mb",
                  "dupont": "ev-dp",
                  "segment": ["ev-seg1", "ev-seg2"],
                  "segment:Widgets": "ev-seg1", "segment:Gadgets": "ev-seg2"},
    )
