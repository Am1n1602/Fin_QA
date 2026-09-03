from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricDef:
    key: str                        # canonical key used everywhere downstream in qa_router
    table: str                       # "financial_metrics" | "financial_facts"
    field: str                        # metric_name / field_name exactly as stored in the DB
    label: str                         # human-readable label for answer templates
    unit_hint: str | None = None        # "pct" | "x" | "currency" | None
    aliases: tuple = field(default_factory=tuple)


METRICS: list[MetricDef] = [
    # --- Profitability / margin ratios (financial_metrics) ---
    MetricDef("npm_pct", "financial_metrics", "npm_pct", "Net Profit Margin", "pct",
              ("npm", "net profit margin", "net margin")),
    MetricDef("pbt_margin_pct", "financial_metrics", "pbt_margin_pct", "PBT Margin", "pct",
              ("pbt margin", "profit before tax margin")),
    MetricDef("ebitda_margin_pct_approx", "financial_metrics", "ebitda_margin_pct_approx",
              "EBITDA Margin (approx.)", "pct", ("ebitda margin",)),
    MetricDef("roe_pct", "financial_metrics", "roe_pct", "Return on Equity (ROE)", "pct",
              ("roe", "return on equity")),
    MetricDef("roa_pct", "financial_metrics", "roa_pct", "Return on Assets (ROA)", "pct",
              ("roa", "return on assets")),
    MetricDef("operating_roce_pct", "financial_metrics", "operating_roce_pct",
              "Operating ROCE (Other Income excluded)", "pct",
              ("operating roce", "roce", "return on capital employed")),
    MetricDef("roce_pct", "financial_metrics", "roce_pct", "ROCE (incl. Other Income)", "pct",
              ("roce including other income", "unadjusted roce")),

    # --- Liquidity / leverage / coverage (financial_metrics) ---
    MetricDef("current_ratio", "financial_metrics", "current_ratio", "Current Ratio", "x",
              ("current ratio",)),
    MetricDef("cash_ratio", "financial_metrics", "cash_ratio", "Cash Ratio", "x",
              ("cash ratio",)),
    MetricDef("debt_to_equity", "financial_metrics", "debt_to_equity", "Debt/Equity", "x",
              ("debt to equity", "debt-to-equity", "leverage ratio")),
    MetricDef("interest_coverage_ratio", "financial_metrics", "interest_coverage_ratio",
              "Interest Coverage", "x", ("interest coverage",)),
    MetricDef("asset_turnover", "financial_metrics", "asset_turnover", "Asset Turnover", "x",
              ("asset turnover",)),
    MetricDef("net_debt_to_operating_ebit", "financial_metrics", "net_debt_to_operating_ebit",
              "Net Debt / Operating EBIT", "x", ("net debt to ebit", "net debt to operating ebit")),
    MetricDef("working_capital_to_assets_pct", "financial_metrics", "working_capital_to_assets_pct",
              "Working Capital / Total Assets", "pct", ("working capital to assets",)),
    MetricDef("equity_to_liabilities_pct", "financial_metrics", "equity_to_liabilities_pct",
              "Equity / Total Liabilities", "pct", ("equity to liabilities",)),

    # --- Valuation (financial_metrics, TTM synthetic filing) ---
    MetricDef("pe_ratio", "financial_metrics", "pe_ratio", "P/E Ratio", "x",
              ("pe ratio", "p e ratio", "price to earnings", "price-to-earnings")),
    MetricDef("pb_ratio", "financial_metrics", "pb_ratio", "P/B Ratio", "x",
              ("pb ratio", "p b ratio", "price to book", "price-to-book")),
    MetricDef("ev_to_sales", "financial_metrics", "ev_to_sales", "EV/Sales", "x",
              ("ev to sales", "enterprise value to sales")),
    MetricDef("earnings_yield_pct", "financial_metrics", "earnings_yield_pct", "Earnings Yield", "pct",
              ("earnings yield",)),
    MetricDef("dividend_yield_pct", "financial_metrics", "dividend_yield_pct", "Dividend Yield", "pct",
              ("dividend yield",)),
    MetricDef("dividend_per_share", "financial_metrics", "dividend_per_share", "Dividend per Share",
              "currency", ("dividend per share", "dps")),
    MetricDef("book_value_per_share", "financial_metrics", "book_value_per_share",
              "Book Value per Share", "currency", ("book value per share", "bvps")),
    MetricDef("enterprise_value", "financial_metrics", "enterprise_value", "Enterprise Value",
              "currency", ("enterprise value",)),
    MetricDef("ttm_eps", "financial_metrics", "ttm_eps", "TTM EPS", "currency", ("ttm eps",)),
    MetricDef("latest_close", "financial_metrics", "latest_close", "Latest Close Price", "currency",
              ("share price", "stock price", "closing price", "latest price")),

    # --- Raw facts (financial_facts) -- see module docstring re: why
    # "dividend" resolves here and not to a computed metric: this is
    # exactly the SESSION_ADDENDUM_2.md HCLTECH-dividend finding that
    # numeric dividend-fact queries should route to financial_facts, not
    # RAG or a ratio. ---
    MetricDef("revenue", "financial_facts", "revenue", "Revenue", None,
              ("revenue", "total revenue", "sales", "turnover", "revenue from operations")),
    MetricDef("net_profit", "financial_facts", "net_profit", "Net Profit", None,
              ("net profit", "profit after tax", "pat", "net income")),
    MetricDef("pbt", "financial_facts", "pbt", "Profit Before Tax", None,
              ("profit before tax",)),
    MetricDef("total_expenses", "financial_facts", "total_expenses", "Total Expenses", None,
              ("total expenses", "total expenditure")),
    MetricDef("total_assets", "financial_facts", "total_assets", "Total Assets", None,
              ("total assets",)),
    MetricDef("total_equity", "financial_facts", "total_equity", "Total Equity", None,
              ("total equity", "shareholders equity", "net worth")),
    MetricDef("eps_basic", "financial_facts", "eps_basic", "EPS (Basic)", None,
              ("eps", "earnings per share", "basic eps")),
    MetricDef("eps_diluted", "financial_facts", "eps_diluted", "EPS (Diluted)", None,
              ("diluted eps",)),
    MetricDef("dividends", "financial_facts", "dividends", "Dividends (as reported)", None,
              ("dividend", "dividends", "dividend declared", "dividend paid")),
    MetricDef("operating_cash_flow", "financial_facts", "operating_cash_flow",
              "Operating Cash Flow", None, ("operating cash flow", "cash from operations")),
    MetricDef("finance_costs", "financial_facts", "finance_costs", "Finance Costs", None,
              ("finance costs", "interest expense", "interest cost")),
]

DEFAULT_COMPARISON_METRICS = [
    "npm_pct", "roe_pct", "operating_roce_pct", "roa_pct",
    "current_ratio", "debt_to_equity", "pe_ratio", "pb_ratio",
]

_BY_KEY = {m.key: m for m in METRICS}

_ALIAS_INDEX: list[tuple[str, str]] = sorted(
    ((alias, m.key) for m in METRICS for alias in m.aliases),
    key=lambda pair: -len(pair[0]),
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def get(key: str) -> MetricDef:
    return _BY_KEY[key]


def resolve_metrics(question: str) -> list[str]:
    normalized_question = _normalize(question)
    claimed_spans: list[tuple[int, int]] = []
    matches: list[tuple[int, str]] = []

    for alias, key in _ALIAS_INDEX:
        pattern = re.compile(r"\b" + re.escape(alias) + r"\b")
        for m in pattern.finditer(normalized_question):
            span = (m.start(), m.end())
            if any(not (span[1] <= c[0] or span[0] >= c[1]) for c in claimed_spans):
                continue  # overlaps an already-claimed (longer) alias match
            claimed_spans.append(span)
            matches.append((span[0], key))

    matches.sort()
    seen: set[str] = set()
    ordered: list[str] = []
    for _, key in matches:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered
