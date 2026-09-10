"""Metric decomposition: DuPont ROE, and a net-margin bridge between two periods."""
from __future__ import annotations

from finqa_v2.engine import derive
from finqa_v2.engine.records import PeriodRecord


def dupont_roe(rec: PeriodRecord) -> dict:
    """ROE = net_profit_margin x asset_turnover x equity_multiplier
       = (net_profit/revenue) x (revenue/total_assets) x (total_assets/total_equity)
    """
    np = rec.get("net_profit")
    rev = rec.get("revenue")
    ta = rec.get("total_assets")
    te = rec.get("total_equity")
    comps: dict[str, float | None] = {
        "net_profit_margin": (np / rev * 100) if (np is not None and rev) else None,
        "asset_turnover": (rev / ta) if (rev is not None and ta) else None,
        "equity_multiplier": (ta / te) if (ta is not None and te) else None,
    }
    if any(v is None for v in comps.values()):
        reconstructed = None
    else:
        # NPM is already a percent; turnover and multiplier are plain ratios, so the
        # product is the ROE percent directly.
        reconstructed = comps["net_profit_margin"] * comps["asset_turnover"] * comps["equity_multiplier"]
    actual = (np / te * 100) if (np is not None and te) else None
    return {
        "components": comps,
        "reconstructed_roe_pct": reconstructed,
        "actual_roe_pct": actual,
        "reconciles": (
            reconstructed is not None and actual is not None
            and abs(reconstructed - actual) <= max(0.01, 5e-4 * abs(actual))
        ),
    }


def net_margin_bridge(prev: PeriodRecord, curr: PeriodRecord) -> dict:
    """Change in net margin (pp) split into a revenue-growth effect and an
    expense-growth effect, holding the other side at the prior period."""
    rp, rc = prev.get("revenue"), curr.get("revenue")
    ep = prev.get("total_expenses")
    ec = curr.get("total_expenses")
    npp, npc = prev.get("net_profit"), curr.get("net_profit")
    if None in (rp, rc, ep, ec, npp, npc) or not rp or not rc:
        return {"available": False}

    margin_prev = npp / rp * 100
    margin_curr = npc / rc * 100
    # profit if only revenue moved (expenses held at prior)
    profit_rev_only = rc - ep
    margin_rev_only = profit_rev_only / rc * 100
    revenue_effect_pp = margin_rev_only - margin_prev
    expense_effect_pp = margin_curr - margin_rev_only
    return {
        "available": True,
        "net_margin_prev_pct": margin_prev,
        "net_margin_curr_pct": margin_curr,
        "net_margin_change_pp": margin_curr - margin_prev,
        "revenue_effect_pp": revenue_effect_pp,
        "expense_effect_pp": expense_effect_pp,
    }


DECOMPOSITIONS = {"roe", "dupont", "net_margin", "net_profit_margin"}
