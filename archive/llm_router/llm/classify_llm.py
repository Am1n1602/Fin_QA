from __future__ import annotations

import json

from .router import LLMRouter

_ALLOWED_INTENTS = (
    "numeric_fact", "trend", "comparison", "ranking", "financial_health",
    "report", "narrative", "complex", "unknown",
)

_SYSTEM_PROMPT = (
    "You classify a financial-research question into exactly one intent. "
    "Reply with ONLY a JSON object, no other text, shaped exactly like:\n"
    '{"intent": "<one of: ' + ", ".join(_ALLOWED_INTENTS) + '>", '
    '"reasoning": "<one short sentence>"}\n'
    "Do not resolve company names or metric phrases yourself -- that is done separately "
    "by a deterministic resolver against the real database. If genuinely unsure, use "
    '"unknown" rather than guessing.'
)


def classify_question_llm(question: str, db_path: str, router: LLMRouter):
    from src.classify import Classification, classify_question as classify_question_rule_based
    from src import companies as companies_mod
    from src import metrics as metrics_mod

    try:
        response = router.generate_for_task(
            "classification", prompt=f"Question: {question}", system=_SYSTEM_PROMPT,
            max_tokens=200, temperature=0.0,
        )
        parsed = json.loads(response.text.strip())
        intent = parsed.get("intent")
        if intent not in _ALLOWED_INTENTS:
            raise ValueError(f"LLM returned an unrecognized intent: {intent!r}")
    except Exception:
        return classify_question_rule_based(question, db_path)

    resolved_companies = companies_mod.resolve_companies(question, db_path)
    resolved_metrics = metrics_mod.resolve_metrics(question)

    return Classification(
        intent=intent,
        companies=resolved_companies,
        metrics=resolved_metrics,
        filing_type="standalone" if "standalone" in question.lower() else "consolidated",
        matched_keywords=[],
        confidence="medium",
        notes=[f"Classified by LLM ({response.provider}/{response.model}): {parsed.get('reasoning', '')}"],
    )
