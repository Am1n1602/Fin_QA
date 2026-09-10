"""LLM prompt + parser for §22 step 4 (candidate-cause generation).

The LLM never classifies and never sees the documents -- it only proposes plausible
business mechanisms from the quantified change and its structured decomposition. All
downstream validation is deterministic.
"""
from __future__ import annotations

import json
import re

CAUSES_SYSTEM = (
    "You are a financial analyst forming hypotheses about why a reported figure moved for "
    "an Indian listed company. Given the quantified change and its structured decomposition, "
    "propose a few DISTINCT, plausible underlying causes (demand, pricing, mix, wage "
    "inflation, input costs, one-off items, investment phase, currency, ...). Do NOT restate "
    "the numbers and do NOT judge whether each cause is true. Return JSON only."
)

_JSON = re.compile(r"\{.*\}", re.S)


def build_causes_prompt(question: str, view) -> str:
    summ = view.summary()
    drivers = "\n".join(f"  {k}: {v}" for k, v in summ.items()) or "  (no driver isolated)"
    return f"""Question: {question}
Quantified change: {view.change.describe()}
Structured decomposition:
{drivers}

Return exactly: {{"causes": ["short cause phrase", "..."]}}
2 to 4 items, each a different mechanism, each under 14 words, no numbers restated.
JSON only."""


def parse_causes(raw: str) -> list[str]:
    m = _JSON.search(raw or "")
    if not m:
        return []
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(d, dict):
        return []
    out: list[str] = []
    for c in d.get("causes") or []:
        s = re.sub(r"\s+", " ", str(c)).strip().rstrip(".")
        if 3 <= len(s) <= 140 and s.lower() not in {x.lower() for x in out}:
            out.append(s)
    return out[:4]
