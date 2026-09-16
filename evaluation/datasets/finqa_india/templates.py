"""Phrase maps + question templates for the FinQA-India generator. See docs/file-guide.md."""
from __future__ import annotations

# raw metrics the engine exposes via get_metric, with a natural phrase
METRICS = {
    "revenue": "revenue",
    "net_profit": "profit after tax",
    "total_income": "total income",
    "total_assets": "total assets",
    "total_equity": "total equity",
    "cash_and_equivalents": "cash and cash equivalents",
    "eps": "earnings per share",
    "ebitda": "EBITDA",
    "ebit": "EBIT",
    "total_debt": "total debt",
}

# ratios via get_ratio
RATIOS = {
    "roe": "return on equity",
    "roce": "return on capital employed",
    "roa": "return on assets",
    "ebitda_margin": "EBITDA margin",
    "ebit_margin": "EBIT margin",
    "net_profit_margin": "net profit margin",
    "pbt_margin": "PBT margin",
    "debt_to_equity": "debt-to-equity ratio",
    "interest_coverage": "interest coverage ratio",
    "current_ratio": "current ratio",
    "asset_turnover": "asset turnover",
    "effective_tax_rate": "effective tax rate",
}

# valuation via get_valuation / get_ratio routing
VALUATION = {
    "pe": "price-to-earnings ratio",
    "pb": "price-to-book ratio",
    "ev_ebitda": "EV/EBITDA multiple",
    "market_cap": "market capitalisation",
    "dividend_yield": "dividend yield",
    "earnings_yield": "earnings yield",
}

GROWTH_METRICS = {
    "revenue": "revenue",
    "net_profit": "profit after tax",
    "total_income": "total income",
}

# a margin/return that has a real two-endpoint series for "why"/"how"
CHANGE_RATIOS = {
    "net_profit_margin": "net profit margin",
    "ebitda_margin": "EBITDA margin",
    "roe": "return on equity",
    "roce": "return on capital employed",
}

# cross-validation mechanisms (management-claim style)
MECHANISMS = [
    ("revenue growth was driven by higher volumes", "volume"),
    ("margins expanded on operating leverage", "operating leverage"),
    ("growth was led by strength in its core segment", "segment"),
    ("profitability improved on a better revenue mix", "mix"),
    ("cost discipline supported the margin", "cost"),
]

# cross-document topics -> the filing section the answer should be grounded in
DOC_TOPICS = {
    "the key risk factors": "risk_factors",
    "demand conditions": "earnings_call",
    "its outlook and guidance": "earnings_call",
    "capital allocation and dividends": "mda",
    "margin outlook": "earnings_call",
    "segment performance": "segment_information",
}

# NB: templates must not start with a word that resolves to a ticker/alias token
# (e.g. "State" -> "State Bank of India" -> SBIN). Keep opening words neutral.
FACTUAL_Q = [
    "What was {name}'s {phrase} in {period}?",
    "What did {name} report for {phrase} in {period}?",
    "According to the financials, what was {name}'s {phrase} in {period}?",
]
NUMERIC_Q = [
    "What was {name}'s {phrase} in {period}?",
    "What was {name}'s {phrase} for {period}?",
]
GROWTH_Q = [
    "How much did {name}'s {phrase} grow year over year in {period}?",
    "What was {name}'s year-over-year {phrase} growth in {period}?",
]
COMPARE2_Q = [
    "Compare {name} and {name2} on {phrase}.",
    "Which of {name} and {name2} has the stronger {phrase}?",
]
COMPARE3_Q = [
    "How do {name}, {name2} and {name3} compare on {phrase}?",
    "Rank {name}, {name2} and {name3} by {phrase}.",
]
WHY_Q = [
    "Why did {name}'s {phrase} {direction} in {period}?",
    "What drove the {direction} in {name}'s {phrase} in {period}?",
]
HOW_Q = [
    "How has {name}'s {phrase} changed year over year?",
    "How did {name}'s {phrase} move in {period}?",
]
CROSSVAL_Q = [
    "{name} management said {mechanism}. Do the reported results support this?",
    "{name} highlighted that {mechanism}. Is this visible in the financial statements?",
]
CROSSDOC_Q = [
    "What does {name} say about {topic} in its filings?",
    "According to its filings, discuss {name}'s {topic}.",
]
SEGMENT_Q = [
    "Break down {name}'s revenue by reportable segment.",
    "What are {name}'s business segments and their revenue contribution?",
]
SEGMENT_DRIVER_Q = [
    "Which segment contributed most to {name}'s revenue growth?",
    "Which reportable segment drove {name}'s revenue change?",
]
DECOMPOSE_Q = [
    "Decompose {name}'s return on equity into its DuPont components.",
    "Break {name}'s ROE into net margin, asset turnover and leverage.",
]
OVERVIEW_Q = [
    "Give a fundamental overview of {name}.",
    "Summarise {name}'s financial position and profitability.",
]


def direction_word(pct: float | None) -> str:
    if pct is None:
        return "change"
    return "rise" if pct > 0 else "decline" if pct < 0 else "hold flat"
