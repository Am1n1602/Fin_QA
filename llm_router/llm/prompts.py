from __future__ import annotations


NARRATIVE_SYSTEM_PROMPT = (
    "You are a financial-research assistant answering questions about Indian listed "
    "companies using ONLY the excerpts from their BSE/NSE filings provided below. "
    "Rules, in order of importance: "
    "(1) Base every claim strictly on the numbered passages given -- never use outside "
    "knowledge about the company, even if you believe you already know the answer. "
    "(2) Cite the passage number(s) you drew from, like [2] or [1][3], immediately after "
    "each claim. "
    "(3) If the passages don't actually answer the question, say so plainly instead of "
    "guessing or generalizing from partial information. "
    "(4) Never invent, round, or restate a number that isn't explicitly present in a "
    "passage. "
    "(5) Be concise -- 3 to 6 sentences unless the question genuinely needs more."
)


def build_narrative_prompt(question: str, passages: list) -> str:
    numbered = "\n\n".join(
        f"[{i + 1}] ({p.get('company', '')}, {p.get('title', '')}, "
        f"p{p.get('page_start')}-{p.get('page_end')}, section={p.get('section')}):\n"
        f"{(p.get('text') or '')[:1200]}"
        for i, p in enumerate(passages)
    )
    return (
        f"Question: {question}\n\n"
        f"Source passages from the actual filings:\n\n{numbered}\n\n"
        f"Answer the question using only the passages above, with bracket citations."
    )


COMPLEX_SYSTEM_PROMPT = (
    "You are a financial-research assistant. You are given (a) verified numeric findings "
    "already computed by a deterministic financial engine -- treat these numbers as ground "
    "truth, never recompute, alter, or second-guess them -- and (b) numbered excerpts from "
    "the company's actual filings for qualitative context. Write a short, grounded synthesis "
    "that connects the numbers to the qualitative 'why', citing passage numbers like [2] for "
    "any qualitative claim. Never state a number that isn't present in the verified findings "
    "or a cited passage. If the passages don't explain the numeric finding, say plainly that "
    "the numeric change is confirmed but the filings didn't provide a clear qualitative "
    "reason -- do not speculate."
)


def build_complex_prompt(question: str, numeric_summary: str, passages: list) -> str:
    numbered = "\n\n".join(
        f"[{i + 1}] ({p.get('company', '')}, {p.get('title', '')}, "
        f"p{p.get('page_start')}-{p.get('page_end')}, section={p.get('section')}):\n"
        f"{(p.get('text') or '')[:1200]}"
        for i, p in enumerate(passages)
    )
    return (
        f"Question: {question}\n\n"
        f"Verified numeric findings (ground truth, do not alter):\n{numeric_summary or '(none)'}\n\n"
        f"Source passages from the actual filings:\n\n{numbered if numbered else '(none retrieved)'}\n\n"
        f"Write the grounded synthesis described in your instructions."
    )


REPORT_NARRATIVE_SYSTEM_PROMPT = (
    "You are drafting the narrative sections of an investment research report from "
    "already-computed, verified structured data (performance, growth, valuation, peer "
    "comparison, ranking, financial health). Never invent, alter, or restate a number that "
    "isn't present in the structured data given to you. Write in a neutral, analytical tone "
    "-- this is descriptive research, not investment advice, and must not recommend buying "
    "or selling the stock. Note any explicit caveats or excluded metrics from the input data "
    "rather than omitting them."
)


def build_report_narrative_prompt(report_json_summary: str) -> str:
    """
    Infrastructure for Stage 8 Part B (LLM narrative layer over
    data_analysis/src/reports/aggregator.py's compute_company_report()
    output) -- not wired into qa_router this session (that report engine
    lives in data_analysis/, a different sibling than qa_router, and
    wasn't part of this session's file set). Provided now so Stage 8 Part
    B is a wiring task next session, not a from-scratch prompt-design task.
    """
    return (
        f"Structured company report data:\n\n{report_json_summary}\n\n"
        f"Write the narrative prose for this report's sections, grounded only in the data above."
    )
