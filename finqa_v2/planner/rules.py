"""Deterministic query planner -- the fallback when the LLM is unavailable, and the
§44 baseline the LLM planner is measured against. Keyword + entity rules only, no LLM.
"""
from __future__ import annotations

import re

from finqa_v2.engine.ratios import SPECS as _RATIO_SPECS
from finqa_v2.engine.ratios import resolve as _resolve_ratio
from finqa_v2.engine.valuation import resolve as _resolve_valuation
from finqa_v2.planner.models import Intent, QueryPlan

_RATIO_NAMES = set(_RATIO_SPECS)

# phrase -> canonical metric/ratio name
_METRIC_PHRASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\breturn on equity\b|\broe\b"), "roe"),
    (re.compile(r"\breturn on capital employed\b|\broce\b"), "roce"),
    (re.compile(r"\breturn on assets\b|\broa\b"), "roa"),
    (re.compile(r"\bebitda margin\b"), "ebitda_margin"),
    (re.compile(r"\boperating margin\b|\bebit margin\b"), "ebit_margin"),
    (re.compile(r"\bnet (profit )?margin\b|\bprofitability\b"), "net_profit_margin"),
    (re.compile(r"\bpbt margin\b"), "pbt_margin"),
    (re.compile(r"\bdebt[ -]?to[ -]?equity\b|\bd/e\b|\bleverage\b|\bgearing\b"), "debt_to_equity"),
    (re.compile(r"\binterest coverage\b"), "interest_coverage"),
    (re.compile(r"\bcurrent ratio\b"), "current_ratio"),
    (re.compile(r"\basset turnover\b"), "asset_turnover"),
    (re.compile(r"\beffective tax rate\b|\btax rate\b"), "effective_tax_rate"),
    (re.compile(r"\bnet interest margin\b|\bnim\b"), "net_interest_margin"),
    # valuation (§11, Phase 15) -- routed to ValuationEngine via get_ratio
    (re.compile(r"\bp\s?/\s?e\b|\bpe ratio\b|\bprice[ -]?to[ -]?earnings\b|\bprice earnings\b"), "pe"),
    (re.compile(r"\bp\s?/\s?b\b|\bpb ratio\b|\bprice[ -]?to[ -]?book\b"), "pb"),
    (re.compile(r"\bev\s?/\s?ebitda\b|\benterprise value\b"), "ev_ebitda"),
    (re.compile(r"\bmarket cap(italis|italiz)?(ation)?\b|\bm\s?cap\b"), "market_cap"),
    (re.compile(r"\bearnings yield\b"), "earnings_yield"),
    (re.compile(r"\bdividend yield\b|\bdiv yield\b"), "dividend_yield"),
    (re.compile(r"\bebitda\b"), "ebitda"),
    (re.compile(r"\bebit\b"), "ebit"),
    (re.compile(r"\brevenue\b|\bsales\b|\btop[ -]?line\b|\bturnover\b"), "revenue"),
    (re.compile(r"\btotal income\b"), "total_income"),
    (re.compile(r"\bnet profit\b|\bpat\b|\bbottom[ -]?line\b|\bprofit after tax\b"), "net_profit"),
    (re.compile(r"\bprofit before tax\b|\bpbt\b"), "pbt"),
    (re.compile(r"\bearnings per share\b|\beps\b"), "eps_basic"),
    (re.compile(r"\boperating cash flow\b|\bcash from operations\b|\bcfo\b"), "operating_cash_flow"),
    (re.compile(r"\bcash and (cash )?equivalents\b|\bcash and bank balances\b|\bcash balance\b"), "cash_and_equivalents"),
    (re.compile(r"\btotal assets\b|\bbalance sheet size\b"), "total_assets"),
    (re.compile(r"\btotal equity\b|\bshareholders'? funds\b|\bnet worth\b"), "total_equity"),
    (re.compile(r"\btotal debt\b|\bborrowings\b"), "total_debt"),
    (re.compile(r"\bcapex\b|\bcapital expenditure\b"), "capex"),
    (re.compile(r"\bdividend\b"), "dividends"),
]

_CROSS_VAL = re.compile(
    r"(is (this|that) (visible|supported|reflected)|do(es)? the (reported )?(financial )?"
    r"(results|statements) support|management (said|says|claimed|highlighted|attributed|noted)"
    r"|as claimed by management|consistent with (the )?(reported )?financials)", re.I)
_CAUSAL = re.compile(
    r"\b(why did|why has|why is|why are|what caused|what drove|what led to|reason(s)? (for|behind)"
    r"|explain (the|why)|driven by|on account of|attributable to)\b", re.I)
_SEGMENT = re.compile(r"\bsegment(s|al)?\b|\bbusiness (line|vertical)s?\b", re.I)
_COMPARE = re.compile(r"\bcompare\b|\bvs\.?\b|\bversus\b|\bcompared (to|with)\b|\bwhich (company|of)\b"
                      r"|\bbetter than\b|\bhigher than\b|\blower than\b|\brelative to\b", re.I)
_RANK = re.compile(r"\brank\b|\branking\b|\bstrongest\b|\bweakest\b|\btop \d+\b|\bbest\b|\bworst\b"
                   r"|\bwhich companies\b|\bleaderboard\b|\bmost (profitable|leveraged)\b", re.I)
_TREND = re.compile(r"\btrend(ed|ing)?\b|\bover the (years|last|past|available)\b|\bhow (has|have)\b"
                    r"|\bhistorical(ly)?\b|\byoy\b|\byear[- ]on[- ]year\b|\byear[- ]over[- ]year\b|\bcagr\b"
                    r"|\bgrow(n|th|ing)?\b|\bgrew\b|\bchang(e|ed|ing)\b|\bmove(d|s)?\b|\bevolv(e|ed|ing)\b", re.I)
_OVERVIEW = re.compile(r"\boverview\b|\bfundamental(s)?\b|\btell me about\b|\bsummary of\b|\bsummaris[ez]e?\b"
                       r"|\bprofile\b|\bhow is .* doing\b", re.I)

_FY_RE = re.compile(r"\bFY\s?'?(\d{2}(?:\d{2})?)(?:\s?Q([1-4]))?\b", re.I)
_FYRANGE_RE = re.compile(r"\b(20\d{2})[-/](\d{2})\b")
_YEAR_RE = re.compile(r"\b(?:in|for|during|ended)\s+(20\d{2})\b", re.I)
_LAST_N = re.compile(r"\b(?:last|past)\s+(one|two|three|four|five|\d+)\s+years?\b", re.I)
_LATEST = re.compile(r"\b(latest|most recent|current|now|today)\b", re.I)
_WORDS_N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


class CompanyMatcher:
    """Precomputes ticker / alias / name lookups once per repos."""

    _STOP_NAME_WORDS = {"ltd", "ltd.", "limited", "the", "of", "and", "&", "india", "co", "co.",
                        "corporation", "company", "industries", "enterprises", "bank"}

    def __init__(self, repos):
        self.by_token: dict[str, str] = {}
        self.multiword: list[tuple[str, str]] = []
        for c in repos.companies.list():
            tkr = c.ticker
            self.by_token[tkr.lower()] = tkr
            for a in c.aliases:
                self.by_token[a.lower()] = tkr
            name = _norm(c.name)
            self.multiword.append((name, tkr))
            words = [w for w in re.split(r"[^a-z0-9]+", name) if w and w not in self._STOP_NAME_WORDS]
            if words:
                self.by_token.setdefault(words[0], tkr)
                if len(words) >= 2:
                    self.multiword.append((" ".join(words[:2]), tkr))
        # drop ambiguous single-word keys (>1 company shares a first word)
        seen: dict[str, set[str]] = {}
        for c in repos.companies.list():
            name = _norm(c.name)
            words = [w for w in re.split(r"[^a-z0-9]+", name) if w and w not in self._STOP_NAME_WORDS]
            if words:
                seen.setdefault(words[0], set()).add(c.ticker)
        for w, tkrs in seen.items():
            if len(tkrs) > 1 and w in self.by_token:
                # keep only if it's also a real ticker
                if self.by_token[w].lower() != w:
                    del self.by_token[w]

    def find(self, question: str) -> list[str]:
        q = " " + _norm(question) + " "
        hits: list[tuple[int, str]] = []
        for phrase, tkr in self.multiword:
            m = re.search(r"\b" + re.escape(phrase) + r"\b", q)
            if m:
                hits.append((m.start(), tkr))
        for m in re.finditer(r"[a-z0-9]+", q):
            tkr = self.by_token.get(m.group(0))
            if tkr:
                hits.append((m.start(), tkr))
        out: list[str] = []
        for _, tkr in sorted(hits, key=lambda x: x[0]):
            if tkr not in out:
                out.append(tkr)
        return out


def _periods(question: str) -> tuple[list[str], list[str]]:
    q = question
    out: list[str] = []
    notes: list[str] = []
    for m in _FY_RE.finditer(q):
        yy = m.group(1)
        fy = int(yy) if len(yy) == 4 else 2000 + int(yy)
        out.append(f"FY{fy}Q{m.group(2)}" if m.group(2) else f"FY{fy}")
    for m in _FYRANGE_RE.finditer(q):
        out.append(f"FY20{m.group(2)}")
    for m in _YEAR_RE.finditer(q):
        out.append(f"FY{m.group(1)}")
    lm = _LAST_N.search(q)
    if lm:
        n = _WORDS_N.get(lm.group(1).lower(), None) or int(lm.group(1))
        notes.append(f"trend depth: last {n} years")
    if _LATEST.search(q) and not out:
        out.append("latest")
    return list(dict.fromkeys(out)), notes


def _metrics(question: str) -> list[str]:
    q = _norm(question)
    out: list[str] = []
    for pat, name in _METRIC_PHRASES:
        if pat.search(q) and name not in out:
            out.append(name)
    return out


def _intent(question: str, companies: list[str], metrics: list[str]) -> Intent:
    q = question
    if _CROSS_VAL.search(q):
        return Intent.CROSS_VALIDATION
    if _SEGMENT.search(q):
        return Intent.SEGMENT
    if _CAUSAL.search(q):
        return Intent.CAUSAL
    if _COMPARE.search(q) or (len(companies) >= 2 and metrics):
        return Intent.COMPARISON
    if _RANK.search(q):
        return Intent.RANKING
    if _OVERVIEW.search(q) and companies:
        return Intent.RESEARCH_OVERVIEW
    if _TREND.search(q) and companies:
        return Intent.TREND
    if companies and metrics:
        return Intent.NUMERIC_FACT
    return Intent.UNKNOWN


def _tools_for(intent: Intent, metrics: list[str]) -> tuple[list[str], bool, bool]:
    has_ratio = any((_resolve_ratio(m) in _RATIO_NAMES) or _resolve_valuation(m) for m in metrics)
    if intent is Intent.NUMERIC_FACT:
        return (["get_ratio" if has_ratio else "get_metric"], False, False)
    if intent is Intent.TREND:
        return (["get_growth", "get_cagr", "get_metric"], False, False)
    if intent is Intent.COMPARISON:
        return (["compare_companies", "get_ratio" if has_ratio else "get_metric"], False, True)
    if intent is Intent.RANKING:
        return (["compare_companies"], False, True)
    if intent is Intent.CAUSAL:
        return (["get_growth", "decompose_metric", "search_documents"], True, True)
    if intent is Intent.CROSS_VALIDATION:
        return (["get_growth", "get_segment_data", "search_documents"], True, True)
    if intent is Intent.SEGMENT:
        return (["get_segment_data"], False, False)
    if intent is Intent.RESEARCH_OVERVIEW:
        return (["get_company", "get_ratio", "get_segment_data", "get_peers"], False, False)
    return ([], False, False)


def plan_with_rules(question: str, *, matcher: CompanyMatcher | None = None,
                    repos=None) -> QueryPlan:
    if matcher is None:
        if repos is None:
            raise ValueError("plan_with_rules needs a matcher or a repos")
        matcher = CompanyMatcher(repos)
    companies = matcher.find(question)
    metrics = _metrics(question)
    periods, notes = _periods(question)
    intent = _intent(question, companies, metrics)
    tools, needs_docs, needs_calc = _tools_for(intent, metrics)
    return QueryPlan(
        question=question, intent=intent, companies=companies, periods=periods,
        metrics=metrics, tools=tools, needs_documents=needs_docs,
        needs_calculation=needs_calc, planner="rules", notes=notes,
    )
