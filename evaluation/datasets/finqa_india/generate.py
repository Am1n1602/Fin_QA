"""Engine-probed candidate generator for FinQA-India. Every numeric row ships with gold
from the deterministic Financial Engine (§11). See docs/file-guide.md."""
from __future__ import annotations

import random
from typing import Any, Iterable

from evaluation.datasets.finqa_india import templates as T

_ANNUAL = "FY2026"
_PRIOR = "FY2025"

_PERIOD_PHRASE = {
    "FY2026": "FY2026", "FY2025": "FY2025",
    "latest_quarter": "the latest quarter", "latest_annual": "the latest financial year",
    "latest": "the latest period",
}


def _pphrase(period: str) -> str:
    return _PERIOD_PHRASE.get(period, period)


# tickers whose punctuation defeats the planner's word-token matcher -> use the plain name
_DISP = {"M&M": "Mahindra & Mahindra", "BAJAJ-AUTO": "Bajaj Auto"}


def _disp(ticker: str) -> str:
    return _DISP.get(ticker, ticker)


def _basis_periods(engine, ticker: str) -> tuple[str, list[str]]:
    for basis in ("consolidated", "standalone"):
        try:
            p = engine.periods(ticker, basis=basis)
        except Exception:
            p = []
        if p:
            return basis, p
    return "consolidated", []


def _rec(**kw) -> dict:
    base = {
        "companies": [], "period": None, "answer_type": "text", "expected_intent": None,
        "should_abstain": False, "gold_spec": None, "reference_value": None,
        "reference_unit": None, "reference_answer": None, "reference_sources": [],
        "tolerance_pct": None, "must_contain": [], "notes": "",
    }
    base.update(kw)
    return base


def _num_row(engine, category, ticker, name, tool, mname, phrase, period, q, *,
             intent="numeric_fact", tol=1.0, kind=None):
    if tool == "get_metric":
        res = engine.get_metric(ticker, mname, period=period)
    elif tool == "get_ratio":
        res = engine.get_ratio(ticker, mname, period=period)
    elif tool == "get_valuation":
        res = engine.get_valuation(ticker, mname, period=period)
    elif tool == "get_growth":
        res = engine.get_growth(ticker, mname, kind=kind or "yoy")
    else:
        return None
    if not res.ok or res.value is None:
        return None
    spec = {"tool": tool, "name": mname, "period": period, "ticker": ticker}
    if tool == "get_growth":
        spec["kind"] = kind or "yoy"
    return _rec(
        category=category, question=q.format(name=_disp(ticker), phrase=phrase, period=_pphrase(period)),
        companies=[ticker], period=period, answer_type="numeric", expected_intent=intent,
        gold_spec=spec, reference_value=round(float(res.value), 6), reference_unit=res.unit,
        tolerance_pct=tol, notes=f"engine {tool}:{mname}",
    )


# --------------------------------------------------------------------------- #
def gen_factual(engine, tickers, rng) -> list[dict]:
    out = []
    for t in tickers:
        for mname, phrase in T.METRICS.items():
            for period in (_ANNUAL, "latest_quarter"):
                q = rng.choice(T.FACTUAL_Q)
                r = _num_row(engine, "factual", t, t, "get_metric", mname, phrase, period, q)
                if r:
                    out.append(r)
    return out


def gen_numerical(engine, tickers, rng) -> list[dict]:
    out = []
    for t in tickers:
        for mname, phrase in {**T.RATIOS, **T.VALUATION}.items():
            tool = "get_valuation" if mname in T.VALUATION else "get_ratio"
            r = _num_row(engine, "numerical", t, t, tool, mname, phrase, _ANNUAL,
                         rng.choice(T.NUMERIC_Q), tol=2.0 if tool == "get_valuation" else 1.0)
            if r:
                out.append(r)
        for mname, phrase in T.GROWTH_METRICS.items():
            r = _num_row(engine, "numerical", t, t, "get_growth", mname, f"{phrase}", _ANNUAL,
                         rng.choice(T.GROWTH_Q), intent="trend", tol=5.0, kind="yoy")
            if r:
                out.append(r)
    return out


def _peers_by_sector(repos, tickers) -> dict[str, list[str]]:
    by_sec: dict[str, list[str]] = {}
    for t in tickers:
        c = repos.companies.resolve(t)
        if c and c.sector:
            by_sec.setdefault(c.sector, []).append(t)
    return by_sec


def gen_comparison(repos, engine, tickers, rng) -> list[dict]:
    out = []
    groups = [g for g in _peers_by_sector(repos, tickers).values() if len(g) >= 2]
    metrics = list(T.RATIOS.items()) + [("pe", "price-to-earnings ratio"), ("market_cap", "market capitalisation")]
    for g in groups:
        for mname, phrase in metrics:
            g2 = sorted(g)
            if len(g2) >= 3 and rng.random() < 0.5:
                trio = rng.sample(g2, 3)
                res = engine.compare_companies(mname, trio, period=_ANNUAL)
                rows = [r for r in (res.get("results") or []) if r.get("value") is not None]
                if len(rows) >= 3:
                    order = " > ".join(f"{r['ticker']} ({round(r['value'], 2)})" for r in rows)
                    out.append(_rec(
                        category="comparison", expected_intent="comparison", answer_type="text",
                        question=rng.choice(T.COMPARE3_Q).format(
                            name=_disp(trio[0]), name2=_disp(trio[1]), name3=_disp(trio[2]), phrase=phrase),
                        companies=trio, must_contain=[trio[0], trio[1]],
                        reference_answer=order, notes=f"compare {mname}"))
            else:
                pair = rng.sample(g2, 2)
                res = engine.compare_companies(mname, pair, period=_ANNUAL)
                rows = [r for r in (res.get("results") or []) if r.get("value") is not None]
                if len(rows) == 2:
                    order = " > ".join(f"{r['ticker']} ({round(r['value'], 2)})" for r in rows)
                    out.append(_rec(
                        category="comparison", expected_intent="comparison", answer_type="text",
                        question=rng.choice(T.COMPARE2_Q).format(
                            name=_disp(pair[0]), name2=_disp(pair[1]), phrase=phrase),
                        companies=pair, must_contain=pair, reference_answer=order,
                        notes=f"compare {mname}"))
    return out


def gen_multi_step(engine, tickers, rng) -> list[dict]:
    out = []
    for t in tickers:
        seg = engine.get_segment_data(t)
        if getattr(seg, "ok", False) and getattr(seg, "rows", None):
            top = max(seg.rows, key=lambda r: getattr(r, "contribution_pct", 0) or 0)
            out.append(_rec(category="multi_step", expected_intent="segment", answer_type="text",
                            question=rng.choice(T.SEGMENT_Q).format(name=_disp(t)),
                            companies=[t], must_contain=[t, "segment"],
                            reference_answer=getattr(top, "segment", None), notes="segment mix"))
        sg = engine.segment_growth(t)
        if getattr(sg, "ok", False) and getattr(sg, "rows", None):
            drv = max(sg.rows, key=lambda r: abs(getattr(r, "share_of_total_change_pct", 0) or 0))
            out.append(_rec(category="multi_step", expected_intent="segment", answer_type="text",
                            question=rng.choice(T.SEGMENT_DRIVER_Q).format(name=_disp(t)),
                            companies=[t], must_contain=[t, "segment"],
                            reference_answer=getattr(drv, "segment", None),
                            notes="segment growth attribution"))
        dq = engine.decompose_metric(t, "roe")
        if dq.ok:
            out.append(_rec(category="multi_step", expected_intent=None, answer_type="text",
                            question=rng.choice(T.DECOMPOSE_Q).format(name=_disp(t)),
                            companies=[t], must_contain=[t], notes="dupont"))
    return out


def gen_why_how(engine, tickers, rng) -> tuple[list[dict], list[dict]]:
    why, how = [], []
    for t in tickers:
        for mname, phrase in T.CHANGE_RATIOS.items():
            g = engine.get_growth(t, mname if mname in ("revenue", "net_profit") else "revenue", kind="yoy")
            # direction from the ratio's own two-endpoint move where possible
            a = engine.get_ratio(t, mname, period=_PRIOR).value
            b = engine.get_ratio(t, mname, period=_ANNUAL).value
            if a is None or b is None:
                continue
            direction = T.direction_word(b - a)
            why.append(_rec(category="why", expected_intent="causal", answer_type="text",
                            question=rng.choice(T.WHY_Q).format(
                                name=_disp(t), phrase=phrase, direction=direction, period=_ANNUAL),
                            companies=[t], period=_ANNUAL, must_contain=[t],
                            reference_answer=f"{phrase} {direction}", notes="causal"))
            how.append(_rec(category="how", expected_intent="trend", answer_type="text",
                            question=rng.choice(T.HOW_Q).format(name=_disp(t), phrase=phrase, period=_ANNUAL),
                            companies=[t], period=_ANNUAL, must_contain=[t], notes="trend"))
    return why, how


def gen_causal_xval(engine, tickers, rng) -> list[dict]:
    out = []
    for t in tickers:
        segtop = None
        seg = engine.get_segment_data(t)
        if getattr(seg, "ok", False) and getattr(seg, "rows", None):
            segtop = getattr(max(seg.rows, key=lambda r: getattr(r, "contribution_pct", 0) or 0),
                             "segment", None)
        for mech, kw in T.MECHANISMS:
            phrase = mech
            mc = [t, kw]
            if kw == "segment":
                if not segtop:
                    continue
                phrase = f"growth was led by the {segtop} segment"
                mc = [t, segtop.split()[0]]
            out.append(_rec(category="causal", expected_intent="cross_validation", answer_type="text",
                            question=rng.choice(T.CROSSVAL_Q).format(name=_disp(t), mechanism=phrase),
                            companies=[t], must_contain=mc, reference_answer=phrase,
                            notes="cross_validation"))
    return out


def gen_cross_document(tickers, rng) -> list[dict]:
    out = []
    for t in tickers:
        for topic, section in T.DOC_TOPICS.items():
            out.append(_rec(category="cross_document", expected_intent=None, answer_type="text",
                            question=rng.choice(T.CROSSDOC_Q).format(name=_disp(t), topic=topic),
                            companies=[t],
                            reference_sources=[{"document": None, "page": None, "section": section}],
                            must_contain=[topic.split()[-1]], notes=f"grounded in {section}"))
    return out


def gen_analytical(engine, tickers, rng) -> list[dict]:
    out = []
    for t in tickers:
        out.append(_rec(category="analytical", expected_intent="research_overview", answer_type="text",
                        question=rng.choice(T.OVERVIEW_Q).format(name=_disp(t)),
                        companies=[t], must_contain=[t], notes="overview"))
        for mname, phrase in list(T.CHANGE_RATIOS.items())[:2]:
            if engine.get_ratio(t, mname, period=_ANNUAL).value is not None:
                out.append(_rec(category="analytical", expected_intent="trend", answer_type="text",
                                question=f"How has {_disp(t)}'s {phrase} trended over the available periods?",
                                companies=[t], must_contain=[t], notes="trend-analytical"))
    return out


_NON_MEMBERS = ["Apple", "Tesla", "Microsoft", "Samsung", "Toyota", "Alphabet"]


def gen_adversarial(engine, tickers, rng) -> list[dict]:
    out = []
    for t in rng.sample(tickers, min(len(tickers), 20)):
        out.append(_rec(category="adversarial", answer_type="abstain", expected_intent="numeric_fact",
                        should_abstain=True, companies=[t], period="FY2015",
                        question=f"What was {_disp(t)}'s revenue in FY2015?",
                        notes="pre-corpus year"))
        out.append(_rec(category="adversarial", answer_type="abstain", expected_intent="numeric_fact",
                        should_abstain=True, companies=[t],
                        question=f"What will {_disp(t)}'s revenue be in FY2028?",
                        notes="forecast out of scope"))
    for nm in _NON_MEMBERS:
        out.append(_rec(category="adversarial", answer_type="abstain", expected_intent=None,
                        should_abstain=True, companies=[],
                        question=f"What was {nm}'s net profit in FY2026?",
                        notes="outside the NIFTY 50 universe"))
    for t in tickers:
        if engine.get_ratio(t, "ebitda_margin", period=_ANNUAL).value is None and \
           engine.get_metric(t, "ebitda", period=_ANNUAL).value is None:
            out.append(_rec(category="adversarial", answer_type="abstain", expected_intent="numeric_fact",
                            should_abstain=True, companies=[t],
                            question=f"What was {_disp(t)}'s EBITDA in FY2026?",
                            notes="bank/insurer files no EBITDA line -> must not fabricate"))
    return out


# --------------------------------------------------------------------------- #
def generate(repos, engine, *, seed: int = 20) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    idx = repos.indices.get_by_name("NIFTY 50")
    tickers = sorted(c.ticker for c in repos.indices.members(idx.index_id))
    why, how = gen_why_how(engine, tickers, rng)
    return {
        "factual": gen_factual(engine, tickers, rng),
        "numerical": gen_numerical(engine, tickers, rng),
        "comparison": gen_comparison(repos, engine, tickers, rng),
        "multi_step": gen_multi_step(engine, tickers, rng),
        "why": why,
        "how": how,
        "causal": gen_causal_xval(engine, tickers, rng),
        "cross_document": gen_cross_document(tickers, rng),
        "analytical": gen_analytical(engine, tickers, rng),
        "adversarial": gen_adversarial(engine, tickers, rng),
    }
