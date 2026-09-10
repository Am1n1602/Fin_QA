"""Prompt construction + response parsing for the LLM planner. The plan is a JSON
object; anything unparseable / invalid makes the caller fall back to the rules planner.
"""
from __future__ import annotations

import json
import re

from finqa_v2.planner.models import Intent, QueryPlan

_SYSTEM = (
    "You are a query planner for a financial-analysis engine over Indian listed companies. "
    "Given a question, output ONLY a JSON object describing how to answer it. Do not answer "
    "the question. Numbers and facts come from tools, not from you."
)

_INTENTS = ", ".join(i.value for i in Intent)


def build_prompt(question: str, *, tool_catalog: list[tuple[str, str]],
                 known_tickers: list[str]) -> str:
    tools = "\n".join(f"  - {name}: {desc}" for name, desc in tool_catalog)
    tickers = ", ".join(known_tickers[:60])
    return f"""Question: {question}

Available tools:
{tools}

Known NSE tickers (use these exact symbols for `companies`): {tickers}

Return a JSON object with these fields:
{{
  "intent": one of [{_INTENTS}],
  "companies": [NSE tickers mentioned or implied, e.g. "TCS"],
  "periods": [e.g. "FY2026", "FY2026Q1", "latest", "latest_annual"] (empty if unspecified),
  "metrics": [canonical metric/ratio names, e.g. "revenue", "roe", "ebitda_margin"],
  "tools": [tool names from the list above, in the order they should run],
  "sub_questions": [decomposed sub-questions if the question is multi-part, else []],
  "needs_documents": true/false (does answering require filing text?),
  "needs_calculation": true/false
}}

Rules:
- "why"/"how did X change" -> intent "causal", include get_growth + search_documents.
- "management said ... is it supported" -> intent "cross_validation".
- comparisons of 2+ companies -> intent "comparison", tool compare_companies.
- a single figure or ratio -> intent "numeric_fact".
- only use tool names from the list. Output JSON only."""


_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def parse_plan(question: str, raw: str, *, valid_tools: set[str],
               valid_tickers: set[str]) -> QueryPlan | None:
    m = _JSON_BLOCK.search(raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    try:
        intent = Intent(str(data.get("intent", "unknown")).strip().lower())
    except ValueError:
        intent = Intent.UNKNOWN

    def _strlist(key):
        v = data.get(key) or []
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []

    companies = [t.upper() for t in _strlist("companies")]
    unknown_co = [t for t in companies if t not in valid_tickers]
    companies = [t for t in companies if t in valid_tickers]

    tools = _strlist("tools")
    dropped = [t for t in tools if t not in valid_tools]
    tools = [t for t in tools if t in valid_tools]

    notes = []
    if unknown_co:
        notes.append(f"planner proposed unknown tickers, dropped: {unknown_co}")
    if dropped:
        notes.append(f"planner proposed unknown tools, dropped: {dropped}")

    return QueryPlan(
        question=question, intent=intent, companies=companies,
        periods=_strlist("periods"), metrics=_strlist("metrics"), tools=tools,
        sub_questions=_strlist("sub_questions"),
        needs_documents=bool(data.get("needs_documents", False)),
        needs_calculation=bool(data.get("needs_calculation", False)),
        planner="llm+repair" if notes else "llm", notes=notes,
    )
