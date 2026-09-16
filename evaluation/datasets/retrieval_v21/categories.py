"""Per-category candidate generators for the v2.1 retrieval benchmark (§5.1).

Each generator yields `Candidate` objects *before* verification: a question plus one or
more `probe.probe()` filter specs. `build.py` runs those probes against the real corpus
and only keeps a candidate once its gold evidence (or, for adversarial/no_evidence items,
the deliberate absence of any) is actually confirmed there.

Every question references a real company drawn from the live `companies` table -- nothing
here is hardcoded to a fixed NIFTY-50 list (§8 in the original v2 roadmap already made that
mistake not-to-repeat).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterator

# tickers whose punctuation reads awkwardly in a plain sentence -- same convention as
# evaluation/datasets/finqa_india/generate.py's _DISP.
_DISP = {"M&M": "Mahindra & Mahindra", "BAJAJ-AUTO": "Bajaj Auto"}


def disp(ticker: str) -> str:
    return _DISP.get(ticker, ticker)


@dataclass(frozen=True)
class ProbeSpec:
    sections: tuple[str, ...] | None = None
    document_types: tuple[str, ...] | None = None
    topics: tuple[str, ...] | None = None
    keyword: str | None = None
    financial_year: int | None = None
    company_id: int | None = None


@dataclass(frozen=True)
class Candidate:
    category: str
    question: str
    company_tickers: tuple[str, ...]
    period: tuple[str, ...]
    probes: tuple[ProbeSpec, ...]
    expect_hits: bool
    difficulty: str
    adversarial_type: str | None = None


# ---------------------------------------------------------------------------
# Phrase pools -- deliberately small and generic; §12's full terminology dictionary is a
# separate later phase, this only needs phrases plausible enough to actually appear.
# ---------------------------------------------------------------------------

NUMERIC_PHRASES = [
    "revenue from operations", "total income", "net profit", "profit after tax",
    "total expenses", "earnings per share", "ebitda", "operating profit",
]
RATIO_PHRASES = [
    "return on equity", "return on capital employed", "net profit margin",
    "operating margin", "debt to equity", "current ratio", "earnings per share",
]
TREND_VERBS = ["grew", "increased", "declined", "decreased", "improved", "moderated"]
NARRATIVE_PHRASES = [
    "strategy", "outlook", "expansion", "capital expenditure", "investment plan",
    "governance", "risk management", "sustainability",
]
CAUSAL_PHRASES = [
    "due to", "driven by", "on account of", "attributable to", "primarily because",
    "owing to", "led to", "as a result of", "mainly due to", "contributed to",
    "impacted by", "on the back of", "helped by", "supported by", "weighed on", "offset by",
]
_CAUSAL_FOCUS = ["revenue", "profit", "margin", "cost"]
MGMT_COMMENTARY_PHRASES = [
    "guidance", "going forward", "management expects", "outlook for", "demand environment",
]
NONEXISTENT_PHRASES = [
    "carbon credit trading revenue", "lunar mining royalties", "cryptocurrency mining margin",
]

_NUMERIC_SECTIONS = ("financial_results",)
_RATIO_SECTIONS = ("financial_results", "notes")
_TREND_SECTIONS = ("mda", "earnings_call")
_NARRATIVE_SECTIONS = ("mda", "risk_factors", "corporate_governance", "board_report")
_CAUSAL_SECTIONS = ("mda", "earnings_call")
_MGMT_SECTIONS = ("earnings_call",)
_SEGMENT_SECTIONS = ("segment_information",)


def _rng_companies(companies: list, rng: random.Random) -> list:
    shuffled = list(companies)
    rng.shuffle(shuffled)
    return shuffled


def gen_numeric(companies: list, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        for phrase in NUMERIC_PHRASES:
            yield Candidate(
                category="numeric",
                question=f"What was {disp(company.ticker)}'s {phrase} according to its financial results?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(sections=_NUMERIC_SECTIONS, keyword=phrase, company_id=company.company_id),),
                expect_hits=True,
                difficulty="easy",
            )


def gen_ratio(companies: list, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        for phrase in RATIO_PHRASES:
            yield Candidate(
                category="ratio",
                question=f"What did {disp(company.ticker)} report for {phrase}?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(sections=_RATIO_SECTIONS, keyword=phrase, company_id=company.company_id),),
                expect_hits=True,
                difficulty="medium",
            )


def gen_trend(companies: list, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        for verb in TREND_VERBS:
            yield Candidate(
                category="trend",
                question=f"Did {disp(company.ticker)}'s performance {verb} during the year, and by how much?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(sections=_TREND_SECTIONS, keyword=verb, company_id=company.company_id),),
                expect_hits=True,
                difficulty="medium",
            )


def gen_narrative(companies: list, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        for phrase in NARRATIVE_PHRASES:
            yield Candidate(
                category="narrative",
                question=f"What did {disp(company.ticker)} disclose about its {phrase}?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(sections=_NARRATIVE_SECTIONS, keyword=phrase, company_id=company.company_id),),
                expect_hits=True,
                difficulty="medium",
            )


def gen_causal(companies: list, rng: random.Random) -> Iterator[Candidate]:
    """Only a minority of companies have any mda/earnings_call chunk containing a causal
    connector at all (a genuine, documented corpus-thinness limit -- see docs/v2-baseline).
    So each candidate tries every causal phrase as an alternative probe (accepted if *any*
    one of them turns up a chunk) and varies the question's focus metric, rather than the
    causal phrase, across attempts for the same company -- otherwise most attempts for a
    company would collapse onto an identical question string and get deduped away."""
    for company in _rng_companies(companies, rng):
        for focus in _CAUSAL_FOCUS:
            yield Candidate(
                category="causal",
                question=f"Why did {disp(company.ticker)}'s {focus} change during the year?",
                company_tickers=(company.ticker,),
                period=(),
                probes=tuple(
                    ProbeSpec(sections=_CAUSAL_SECTIONS, keyword=phrase, company_id=company.company_id)
                    for phrase in CAUSAL_PHRASES
                ),
                expect_hits=True,
                difficulty="hard",
            )


def gen_management_commentary(companies: list, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        for phrase in MGMT_COMMENTARY_PHRASES:
            yield Candidate(
                category="management_commentary",
                question=f"What did {disp(company.ticker)}'s management say about {phrase}?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(sections=_MGMT_SECTIONS, keyword=phrase, company_id=company.company_id),),
                expect_hits=True,
                difficulty="medium",
            )


def gen_table(companies: list, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        for phrase in NUMERIC_PHRASES:
            yield Candidate(
                category="table",
                question=f"Which table in {disp(company.ticker)}'s filings reports its {phrase}?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(topics=("table",), keyword=phrase, company_id=company.company_id),),
                expect_hits=True,
                difficulty="easy",
            )


def gen_segment(companies: list, segments_by_company: dict, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        segs = segments_by_company.get(company.company_id, [])
        rng.shuffle(segs)
        for seg in segs:
            yield Candidate(
                category="segment",
                question=f"Is {seg.name} one of {disp(company.ticker)}'s reported business segments?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(sections=_SEGMENT_SECTIONS, keyword=seg.name, company_id=company.company_id),),
                expect_hits=True,
                difficulty="easy",
            )


def gen_comparison(companies: list, rng: random.Random) -> Iterator[Candidate]:
    shuffled = _rng_companies(companies, rng)
    for i in range(0, len(shuffled) - 1, 2):
        a, b = shuffled[i], shuffled[i + 1]
        for phrase in NUMERIC_PHRASES:
            yield Candidate(
                category="comparison",
                question=f"Compare {disp(a.ticker)} and {disp(b.ticker)} on {phrase}.",
                company_tickers=(a.ticker, b.ticker),
                period=(),
                probes=(
                    ProbeSpec(sections=_NUMERIC_SECTIONS, keyword=phrase, company_id=a.company_id),
                    ProbeSpec(sections=_NUMERIC_SECTIONS, keyword=phrase, company_id=b.company_id),
                ),
                expect_hits=True,
                difficulty="hard",
            )


def gen_multi_hop(companies: list, segments_by_company: dict, rng: random.Random) -> Iterator[Candidate]:
    for company in _rng_companies(companies, rng):
        segs = segments_by_company.get(company.company_id, [])
        if not segs:
            continue
        seg = rng.choice(segs)
        for phrase in NUMERIC_PHRASES:
            yield Candidate(
                category="multi_hop",
                question=(f"How does {disp(company.ticker)}'s {seg.name} segment relate to its "
                          f"overall {phrase}?"),
                company_tickers=(company.ticker,),
                period=(),
                probes=(
                    ProbeSpec(sections=_SEGMENT_SECTIONS, keyword=seg.name, company_id=company.company_id),
                    ProbeSpec(sections=_NUMERIC_SECTIONS, keyword=phrase, company_id=company.company_id),
                ),
                expect_hits=True,
                difficulty="hard",
            )


def gen_cross_document(companies: list, rng: random.Random) -> Iterator[Candidate]:
    """Needs a probe.distinct_document_types() lookup, so build.py resolves the actual
    document_type list per (company, phrase) itself before accepting -- this generator
    only proposes candidates; ProbeSpec.document_types is filled in by build.py once it
    knows which >=2 document types actually co-occur."""
    for company in _rng_companies(companies, rng):
        for phrase in NUMERIC_PHRASES + NARRATIVE_PHRASES:
            yield Candidate(
                category="cross_document",
                question=(f"What does {disp(company.ticker)} disclose about {phrase} across its "
                          f"transcripts and filings?"),
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(keyword=phrase, company_id=company.company_id),),
                expect_hits=True,
                difficulty="hard",
            )


def gen_adversarial(companies: list, rng: random.Random) -> Iterator[Candidate]:
    shuffled = _rng_companies(companies, rng)
    for company in shuffled:
        # wrong_period: a year well before this corpus's earliest coverage (FY2025+).
        yield Candidate(
            category="adversarial",
            question=f"What was {disp(company.ticker)}'s revenue from operations in FY2015?",
            company_tickers=(company.ticker,),
            period=("FY2015",),
            probes=(ProbeSpec(sections=_NUMERIC_SECTIONS, keyword="revenue from operations",
                              financial_year=2015, company_id=company.company_id),),
            expect_hits=False,
            difficulty="hard",
            adversarial_type="wrong_period",
        )
    # out_of_universe: a real, well-known company that is not one of ours.
    for name in ("Apple Inc", "Amazon.com", "Berkshire Hathaway", "Toyota Motor Corporation"):
        yield Candidate(
            category="adversarial",
            question=f"What was {name}'s revenue from operations in its most recent annual report?",
            company_tickers=(),
            period=(),
            probes=(ProbeSpec(sections=_NUMERIC_SECTIONS, keyword="revenue from operations"),),
            expect_hits=False,
            difficulty="hard",
            adversarial_type="out_of_universe",
        )


def gen_no_evidence(companies: list, rng: random.Random) -> Iterator[Candidate]:
    shuffled = _rng_companies(companies, rng)
    for company in shuffled:
        yield Candidate(
            category="no_evidence",
            question=f"What will {disp(company.ticker)}'s revenue be in FY2030?",
            company_tickers=(company.ticker,),
            period=("FY2030",),
            probes=(ProbeSpec(keyword="revenue", financial_year=2030, company_id=company.company_id),),
            expect_hits=False,
            difficulty="hard",
            adversarial_type="forecast_not_in_corpus",
        )
    for company in shuffled:
        for phrase in NONEXISTENT_PHRASES:
            yield Candidate(
                category="no_evidence",
                question=f"What was {disp(company.ticker)}'s {phrase}?",
                company_tickers=(company.ticker,),
                period=(),
                probes=(ProbeSpec(keyword=phrase, company_id=company.company_id),),
                expect_hits=False,
                difficulty="hard",
                adversarial_type="nonexistent_metric",
            )
