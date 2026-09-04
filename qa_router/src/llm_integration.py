from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# qa_router/src/llm_integration.py -> qa_router/src -> qa_router -> project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LLM_ROUTER_DIR = _PROJECT_ROOT / "llm_router"

_router = None
_router_init_failed = False


def _get_router():
    global _router, _router_init_failed
    if _router is not None or _router_init_failed:
        return _router
    try:
        if str(_LLM_ROUTER_DIR) not in sys.path:
            sys.path.insert(0, str(_LLM_ROUTER_DIR))
        from llm.config import load_llm_config
        from llm.router import LLMRouter

        _router = LLMRouter(load_llm_config())
    except Exception:
        _router_init_failed = True
        _router = None
    return _router


_NUMBER_PATTERN = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])\d{3,}(?:\.\d+)?(?![\w])")
_CURRENCY_GLUE_PATTERN = re.compile(r"(Rs\.?|INR|US\$|\$|GBP|EUR)(?=\d)", re.IGNORECASE)


def _normalize_currency_glue(text: str) -> str:
    return _CURRENCY_GLUE_PATTERN.sub(r"\1 ", text or "")


def _extract_numbers(text: str) -> set:
    """Comma-normalized set of 3+ digit numeric tokens found in `text`."""
    text = _normalize_currency_glue(text)
    return {m.replace(",", "") for m in _NUMBER_PATTERN.findall(text)}

_UNIT_FAMILIES = {
    "crore": re.compile(r"\bcrores?\b", re.IGNORECASE),
    "million": re.compile(r"\bmillions?\b|\bmn\b", re.IGNORECASE),
    "lakh": re.compile(r"\blakhs?\b|\blac\b", re.IGNORECASE),
    "billion": re.compile(r"\bbillions?\b|\bbn\b", re.IGNORECASE),
}


def _units_used(text: str) -> set:
    """Set of currency-scale-word families (crore/million/lakh/billion) found in `text`."""
    text = text or ""
    return {name for name, pattern in _UNIT_FAMILIES.items() if pattern.search(text)}


def _check_unit_consistency(answer_text: str, source_texts: list) -> tuple:
    combined_source = " ".join(source_texts)
    answer_units = _units_used(answer_text)
    source_units = _units_used(combined_source)
    unsupported = answer_units - source_units
    return (len(unsupported) == 0, unsupported)


def _verify_numeric_fidelity(answer_text: str, source_texts: list) -> tuple:
    combined_source = " ".join(source_texts)
    source_numbers = _extract_numbers(combined_source)
    answer_numbers = _extract_numbers(answer_text)
    unsupported = answer_numbers - source_numbers
    return (len(unsupported) == 0, unsupported)


_NARRATIVE_MAX_TOKENS = 900
_COMPLEX_MAX_TOKENS = 900

_SENTENCE_END_CHARS = (".", "!", "?", '"', "]", ")")


def _warn_if_truncated(answer_text: str, provider: str, model: str, task_label: str) -> None:
    stripped = (answer_text or "").rstrip()
    if stripped and not stripped.endswith(_SENTENCE_END_CHARS):
        logger.warning(
            "%s answer from %s/%s does not end on sentence-ending punctuation -- "
            "possible truncation (max_tokens reached mid-generation). Answer still "
            "passed the numeric-fidelity check and was NOT rejected -- this is a "
            "completeness signal only, not a correctness one. Last 80 chars: %r",
            task_label, provider, model, stripped[-80:],
        )

_STATUS_OK = "ok"
_STATUS_UNAVAILABLE = "unavailable"
_STATUS_REJECTED_NUMERIC = "rejected_numeric"
_STATUS_REJECTED_UNIT = "rejected_unit"


def synthesize_narrative_answer(question: str, passages: list) -> tuple:
    router = _get_router()
    if router is None or not passages:
        return None, _STATUS_UNAVAILABLE
    try:
        from llm.prompts import NARRATIVE_SYSTEM_PROMPT, build_narrative_prompt

        prompt = build_narrative_prompt(question, passages)
        response = router.generate_for_task(
            "narrative_synthesis", prompt=prompt, system=NARRATIVE_SYSTEM_PROMPT,
            max_tokens=_NARRATIVE_MAX_TOKENS, temperature=0.2,
        )
        source_texts = [p.get("text", "") for p in passages]
        ok, unsupported = _verify_numeric_fidelity(response.text, source_texts)
        if not ok:
            logger.warning(
                "Rejected LLM narrative synthesis (%s/%s): number(s) %s in the answer do not appear "
                "in any cited source passage -- falling back to the deterministic passage answer.",
                response.provider, response.model, sorted(unsupported),
            )
            return None, _STATUS_REJECTED_NUMERIC
        unit_ok, unsupported_units = _check_unit_consistency(response.text, source_texts)
        if not unit_ok:
            logger.warning(
                "Rejected LLM narrative synthesis (%s/%s): unit(s) %s used in the answer do not "
                "appear anywhere in the cited source passages -- likely a unit hallucination (e.g. "
                "reporting crores as million) -- falling back to the deterministic passage answer.",
                response.provider, response.model, sorted(unsupported_units),
            )
            return None, _STATUS_REJECTED_UNIT
        _warn_if_truncated(response.text, response.provider, response.model, "Narrative synthesis")
        return response.text, _STATUS_OK
    except Exception:
        return None, _STATUS_UNAVAILABLE


def synthesize_complex_answer(question: str, numeric_summary: str, passages: list) -> tuple:
    router = _get_router()
    if router is None:
        return None, _STATUS_UNAVAILABLE
    try:
        from llm.prompts import COMPLEX_SYSTEM_PROMPT, build_complex_prompt

        prompt = build_complex_prompt(question, numeric_summary, passages)
        response = router.generate_for_task(
            "complex_qa", prompt=prompt, system=COMPLEX_SYSTEM_PROMPT,
            max_tokens=_COMPLEX_MAX_TOKENS, temperature=0.2,
        )
        source_texts = [p.get("text", "") for p in passages] + [numeric_summary or ""]
        ok, unsupported = _verify_numeric_fidelity(response.text, source_texts)
        if not ok:
            logger.warning(
                "Rejected LLM complex-QA synthesis (%s/%s): number(s) %s in the answer do not appear "
                "in the verified numeric findings or any cited source passage -- falling back to the "
                "deterministic answer.",
                response.provider, response.model, sorted(unsupported),
            )
            return None, _STATUS_REJECTED_NUMERIC
        unit_ok, unsupported_units = _check_unit_consistency(response.text, source_texts)
        if not unit_ok:
            logger.warning(
                "Rejected LLM complex-QA synthesis (%s/%s): unit(s) %s used in the answer do not "
                "appear anywhere in the verified numeric findings or any cited source passage -- "
                "likely a unit hallucination (e.g. reporting crores as million) -- falling back to "
                "the deterministic answer.",
                response.provider, response.model, sorted(unsupported_units),
            )
            return None, _STATUS_REJECTED_UNIT
        _warn_if_truncated(response.text, response.provider, response.model, "Complex-QA synthesis")
        return response.text, _STATUS_OK
    except Exception:
        return None, _STATUS_UNAVAILABLE
