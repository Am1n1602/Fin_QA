from __future__ import annotations

from src import metrics as metrics_mod

DECLINE_WORDS = (
    "decline", "declined", "declining", "decrease", "decreased", "fell", "fall", "falling",
    "dropped", "drop", "lower", "worsened", "weak", "weakness", "reduced", "reduction",
    "down", "slowdown", "slowed",
)
INCREASE_WORDS = (
    "increase", "increased", "grew", "growth", "improved", "improvement", "higher",
    "rose", "rise", "rising", "strong", "strength", "expanded", "expansion", "up",
)

CONNECTOR_PHRASES = ("primarily due to", "on account of", "attributable to", "mainly on account of")

GENERIC_CAUSE_PHRASES = ("exceptional item", "one-time item", "provision", "impairment")

_MAX_VARIANTS = 6


def expand_narrative_query(question: str, metric_keys: list[str]) -> list[str]:
    text = question.lower()
    direction = None
    if any(w in text for w in DECLINE_WORDS):
        direction = "decrease"
    elif any(w in text for w in INCREASE_WORDS):
        direction = "increase"
    if direction is None:
        return []

    metric_labels = [metrics_mod.get(k).label.lower() for k in metric_keys]
    variants: list[str] = []

    if metric_labels:
        for label in metric_labels[:2]:  # cap -- don't blow up the variant count on a multi-metric question
            variants.append(f"{direction} in {label}")
            variants.append(f"{label} {direction}d")
    else:
        variants.append(f"{direction} in profit after tax")
        variants.append("profit after tax decreased" if direction == "decrease" else "profit after tax increased")

    if direction == "decrease":
        variants.extend(GENERIC_CAUSE_PHRASES)

    anchor = metric_labels[0] if metric_labels else "profit"
    for phrase in CONNECTOR_PHRASES:
        variants.append(f"{anchor} {phrase}")

    seen: set[str] = set()
    ordered: list[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered[:_MAX_VARIANTS]