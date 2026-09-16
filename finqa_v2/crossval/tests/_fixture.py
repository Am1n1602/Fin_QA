"""Cross-validation fixtures: the shared engine seed + a hand-built decomposition view
carrying segments, for the check-level unit tests.
"""
from __future__ import annotations

from finqa_v2.engine import FinancialEngine
from finqa_v2.engine.tests._fixture import seed as seed_engine
from finqa_v2.hypothesis.decompose import DecompositionView
from finqa_v2.hypothesis.models import MetricChange
from finqa_v2.sqlite import SqliteRepositories


def engine_repos():
    repos = SqliteRepositories(":memory:")
    seed_engine(repos)                       # company TEST, FY2025 + FY2026 annual
    return FinancialEngine(repos), repos


def growth_view(direction: str = "increase") -> DecompositionView:
    """A revenue increase led by one segment; margin widened on cost leverage."""
    up = direction == "increase"
    change = MetricChange(
        ticker="ACME", metric="revenue", basis="consolidated",
        from_period="FY2025", to_period="FY2026",
        from_value=1000.0, to_value=1120.0 if up else 900.0,
        abs_change=120.0 if up else -100.0, pct_change=12.0 if up else -10.0,
        evidence_id="ev-change",
    )
    return DecompositionView(
        change=change,
        components={"revenue": {"pct": 12.0 if up else -10.0},
                    "employee_expense": {"pct": 6.0}},
        margin_bridge={"net_margin_change_pp": 1.8 if up else -1.8,
                       "revenue_effect_pp": 0.4, "expense_effect_pp": 1.4 if up else -1.4},
        segments=[{"segment": "Banking Financial Services and Insurance",
                   "abs": 90.0, "pct": 15.0, "share_pct": 75.0},
                  {"segment": "Manufacturing", "abs": 30.0, "pct": 4.0, "share_pct": 25.0}],
        evidence={"margin_bridge": "ev-mb",
                  "segment:Banking Financial Services and Insurance": "ev-seg-bfsi",
                  "segment:Manufacturing": "ev-seg-mfg"},
    )
