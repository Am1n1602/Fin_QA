from __future__ import annotations

import re
from dataclasses import dataclass, field

from src import companies as companies_mod
from src import metrics as metrics_mod

INTENT_NUMERIC_FACT = "numeric_fact"
INTENT_TREND = "trend"
INTENT_COMPARISON = "comparison"
INTENT_RANKING = "ranking"
INTENT_FINANCIAL_HEALTH = "financial_health"
INTENT_REPORT = "report"
INTENT_NARRATIVE = "narrative"
INTENT_COMPLEX = "complex"
INTENT_UNKNOWN = "unknown"


@dataclass
class Classification:
    intent: str
    companies: list = field(default_factory=list)
    metrics: list = field(default_factory=list)
    filing_type: str = "consolidated"
    matched_keywords: list = field(default_factory=list)
    confidence: str = "low"    # "low" | "medium" | "high" -- coarse, not a probability
    notes: list = field(default_factory=list)


def _contains_any(text: str, phrases: tuple) -> list[str]:
    return [p for p in phrases if p in text]


_REPORT_KEYWORDS = ("research report", "full report", "investment report", "generate a report",
                     "write a report", "company report", "detailed report")

_HEALTH_KEYWORDS = ("piotroski", "altman", "z-score", "z score", "f-score", "f score",
                     "financial health", "financially healthy", "financially strong",
                     "financially weak", "accounting risk", "earnings quality",
                     "earnings consistency", "balance sheet strength")

_RANKING_ONLY_KEYWORDS = ("rank the", "ranking of", "overall rank", "fundamentally strongest",
                           "fundamentally best", "best fundamentals", "overall score",
                           "top ranked", "which is the best company", "which is the strongest",
                           "rank companies", "rank all")

_COMPARISON_KEYWORDS = ("compare", "comparison", " vs ", " vs. ", " versus ", "compared to",
                         "against its peers", "which company has", "which has higher",
                         "which has lower", "who has the highest", "who has the lowest",
                         "leader in", "better than")

_NARRATIVE_KEYWORDS = ("why did", "why has", "why is", "what does the filing say",
                        "management commentary", "risk factor", "litigation",
                        "legal proceeding", "outlook", "guidance", "explain why",
                        "reason for", "reason behind", "discuss", "commentary on",
                        "auditor", "qualitative", "narrative", "mentioned in the filing",
                        "says about", "according to the filing", "notes to accounts",
                        "what happened")

_TREND_KEYWORDS = ("trend", "over the years", "historically", "history of", "over time",
                    "growth", "yoy", "year over year", "year-over-year", "quarterly trend",
                    "how has", "past 5 years", "past five years", "last few years",
                    "over the last", "over the past")

_STANDALONE_KEYWORDS = ("standalone",)


def _detect_filing_type(text: str) -> str:
    return "standalone" if any(k in text for k in _STANDALONE_KEYWORDS) else "consolidated"


def classify_question(question: str, db_path: str) -> Classification:
    text = " " + question.lower().strip() + " "  # padded so " vs " etc. match at the edges too
    text = re.sub(r"\s+", " ", text)

    resolved_companies = companies_mod.resolve_companies(question, db_path)
    resolved_metrics = metrics_mod.resolve_metrics(question)
    filing_type = _detect_filing_type(text)

    report_hits = _contains_any(text, _REPORT_KEYWORDS)
    health_hits = _contains_any(text, _HEALTH_KEYWORDS)
    ranking_hits = _contains_any(text, _RANKING_ONLY_KEYWORDS)
    comparison_hits = _contains_any(text, _COMPARISON_KEYWORDS)
    narrative_hits = _contains_any(text, _NARRATIVE_KEYWORDS)
    trend_hits = _contains_any(text, _TREND_KEYWORDS)

    numeric_signal = bool(resolved_companies) and bool(resolved_metrics)
    narrative_signal = bool(narrative_hits)

    if report_hits and resolved_companies:
        return Classification(INTENT_REPORT, resolved_companies, resolved_metrics, filing_type,
                               report_hits, "high")

    if health_hits and resolved_companies:
        return Classification(INTENT_FINANCIAL_HEALTH, resolved_companies, resolved_metrics,
                               filing_type, health_hits, "high")

    if narrative_signal and (numeric_signal or comparison_hits or trend_hits):
        return Classification(
            INTENT_COMPLEX, resolved_companies, resolved_metrics, filing_type,
            narrative_hits + comparison_hits + trend_hits, "medium",
            notes=["Matched both a narrative trigger and a numeric/comparison/trend trigger -- "
                   "routed to multiple engines, see qa.py's _handle_complex()."],
        )

    if ranking_hits and not resolved_metrics:
        return Classification(INTENT_RANKING, resolved_companies, resolved_metrics, filing_type,
                               ranking_hits, "high")

    if comparison_hits or (ranking_hits and resolved_metrics) or \
            (len(resolved_companies) >= 2 and resolved_metrics and not narrative_signal):
        return Classification(INTENT_COMPARISON, resolved_companies, resolved_metrics, filing_type,
                               comparison_hits or ranking_hits, "high" if comparison_hits else "medium")

    if ranking_hits:
        return Classification(INTENT_RANKING, resolved_companies, resolved_metrics, filing_type,
                               ranking_hits, "medium")

    if narrative_signal:
        return Classification(INTENT_NARRATIVE, resolved_companies, resolved_metrics, filing_type,
                               narrative_hits, "high")

    if trend_hits and resolved_companies:
        return Classification(INTENT_TREND, resolved_companies, resolved_metrics, filing_type,
                               trend_hits, "high")

    if numeric_signal:
        return Classification(INTENT_NUMERIC_FACT, resolved_companies, resolved_metrics, filing_type,
                               [], "high" if len(resolved_companies) == 1 else "medium")

    if resolved_companies and not resolved_metrics:
        return Classification(
            INTENT_UNKNOWN, resolved_companies, resolved_metrics, filing_type, [], "low",
            notes=["Recognized a company but no metric or clear intent keyword -- ask for a "
                   "specific metric, or a 'why'/'compare'/'rank' phrasing."],
        )

    return Classification(
        INTENT_UNKNOWN, resolved_companies, resolved_metrics, filing_type, [], "low",
        notes=["No company, metric, or intent keyword recognized."],
    )
