"""Valuation ratios (§11): P/E, P/B, EV/EBITDA, market cap, earnings & dividend yield.

Needs share prices (Phase 15 `finqa_v2.prices`) aligned to the period end. A missing
price or a missing input yields value=None + a `limitations` entry -- never a guess (§9).
"""
from __future__ import annotations

from finqa_v2.engine import derive

_ALIASES = {
    "pe": "pe", "p/e": "pe", "pe_ratio": "pe", "price_to_earnings": "pe", "price_earnings": "pe",
    "pb": "pb", "p/b": "pb", "pb_ratio": "pb", "price_to_book": "pb", "price_book": "pb",
    "ev_ebitda": "ev_ebitda", "ev/ebitda": "ev_ebitda", "enterprise_value_to_ebitda": "ev_ebitda",
    "market_cap": "market_cap", "mcap": "market_cap", "marketcap": "market_cap",
    "market_capitalisation": "market_cap", "market_capitalization": "market_cap",
    "earnings_yield": "earnings_yield",
    "dividend_yield": "dividend_yield", "div_yield": "dividend_yield",
}
NAMES = ("pe", "pb", "ev_ebitda", "market_cap", "earnings_yield", "dividend_yield")
_UNIT = {"pe": "x", "pb": "x", "ev_ebitda": "x", "market_cap": "INR",
         "earnings_yield": "pct", "dividend_yield": "pct"}
_FORMULA = {
    "pe": "share_price / eps_basic",
    "pb": "market_cap / total_equity",
    "ev_ebitda": "(market_cap + net_debt) / ebitda",
    "market_cap": "share_price * shares_outstanding",
    "earnings_yield": "eps_basic / share_price * 100",
    "dividend_yield": "(dividends / shares_outstanding) / share_price * 100",
}


def resolve(name: str | None) -> str | None:
    return _ALIASES.get((name or "").strip().lower())


class ValuationEngine:
    def __init__(self, repos, fin_engine):
        self._repos = repos
        self._fin = fin_engine

    def get(self, ticker: str, kind: str, *, basis="consolidated", period="latest_annual"):
        from finqa_v2.engine.engine import EngineResult, FactRef

        canon = resolve(kind)
        company = self._fin._company(ticker)
        base = EngineResult("valuation", canon or kind, None, unit=_UNIT.get(canon),
                            company=company.ticker, basis=str(basis),
                            formula=_FORMULA.get(canon))
        if canon is None:
            return _with(base, f"unknown valuation metric {kind!r}; known: {', '.join(NAMES)}")

        records = self._fin._records(company.company_id, basis)
        rec = self._fin._select(records, period, lambda r: r.is_annual)
        if rec is None:
            return _with(base, f"no annual period for {company.ticker} (period={period})")
        if rec.period_end is None:
            return _with(base, f"annual period {rec.label} has no end date to price against")

        price = self._repos.prices.on_or_before(company.company_id, rec.period_end)
        if price is None or price.close is None:
            return _with(base, f"no share price within 14 days of {rec.period_end} for "
                               f"{company.ticker} (import prices: python -m finqa_v2.prices.import_prices)")

        p = price.close
        shares = derive.shares_outstanding(rec.values)
        eps = rec.get("eps_basic") if rec.get("eps_basic") is not None else rec.get("eps_diluted")
        equity = rec.get("total_equity")
        ebitda = derive.ebitda(rec.values)
        net_debt = derive.net_debt(rec.values)
        dividends = rec.get("dividends")
        mcap = (p * shares) if shares else None
        notes: list[str] = []

        # Banks / any company that doesn't file EPS but does file a share count:
        # EPS = net_profit / shares  -> P/E collapses to market_cap / net_profit.
        np_ = rec.get("net_profit")
        if eps is None and np_ is not None and shares:
            eps = np_ / shares
            notes.append("EPS derived as net_profit / shares (no reported EPS -- bank / "
                         "non-standard P&L format)")
        # Banks have no EBITDA line; use pre-provision operating profit (PPOP) as the
        # EBITDA-equivalent so EV/EBITDA becomes a P/PPOP proxy.
        if ebitda is None and rec.get("bank_operating_profit") is not None:
            ebitda = rec.get("bank_operating_profit")
            notes.append("EBITDA proxied by bank pre-provision operating profit; EV/EBITDA "
                         "here is a price / PPOP proxy (EV is not meaningful for a bank)")

        table = {
            "market_cap":     (mcap, [("share_price", p), ("shares_outstanding", shares)]),
            "pe":             ((p / eps) if (eps and eps > 0) else None,
                               [("share_price", p), ("eps_basic", eps)]),
            "earnings_yield": ((eps / p * 100) if (eps is not None and p) else None,
                               [("eps_basic", eps), ("share_price", p)]),
            "pb":             ((mcap / equity) if (mcap is not None and equity and equity > 0) else None,
                               [("market_cap", mcap), ("total_equity", equity)]),
            "ev_ebitda":      (((mcap + (net_debt or 0.0)) / ebitda)
                               if (mcap is not None and ebitda and ebitda > 0) else None,
                               [("market_cap", mcap), ("net_debt", net_debt), ("ebitda", ebitda)]),
            "dividend_yield": (((dividends / shares) / p * 100)
                               if (dividends is not None and shares and p) else None,
                               [("dividends", dividends), ("shares_outstanding", shares),
                                ("share_price", p)]),
        }
        val, inputs = table[canon]
        if val is None:
            missing = [n for n, v in inputs if v in (None, 0) or v == 0.0]
            return _with(base, f"{canon}: inputs unavailable ({', '.join(missing) or 'n/a'}) "
                               f"for {company.ticker} {rec.label}")
        relevant = {"pe": notes[:1] if any("EPS" in n for n in notes) else [],
                    "earnings_yield": notes[:1] if any("EPS" in n for n in notes) else [],
                    "ev_ebitda": [n for n in notes if "EBITDA" in n]}.get(canon, [])
        return EngineResult(
            "valuation", canon, val, unit=_UNIT[canon], company=company.ticker, basis=rec.basis,
            period=rec.label, formula=_FORMULA[canon],
            inputs=tuple(FactRef(n, v, rec.label, None) for n, v in inputs if v is not None),
            components={"share_price": p, "price_date": price.price_date.isoformat()},
            limitations=tuple(relevant),
        )


def _with(res, msg: str):
    from finqa_v2.engine.engine import EngineResult

    return EngineResult(res.kind, res.name, None, unit=res.unit, company=res.company,
                        basis=res.basis, formula=res.formula,
                        limitations=res.limitations + (msg,))
