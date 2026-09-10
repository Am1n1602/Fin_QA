"""Tokenizer for lexical retrieval over financial filings.

Lowercase word/number tokens; keeps 'fy2026', '31', 'ebitda' intact; drops a small
stoplist and 1-char tokens. Deliberately simple and deterministic.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")

_STOP = frozenset(
    "a an the and or of to in for on at by is are was were be been being as it its this "
    "that these those with from into out over under such not no nor but if then than we "
    "our you your they their he she his her have has had do does did will would shall "
    "should can could may might must about above below up down off per via which who whom "
    "whose what when where why how also any all each other some more most only own same so "
    "very s t re ve ll d m".split()
)


def tokenize(text: str) -> list[str]:
    return [tok for tok in _TOKEN.findall((text or "").lower()) if len(tok) > 1 and tok not in _STOP]
