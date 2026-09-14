"""Financial terminology dictionary + intent-aware query expansion (§11/§12).

`expand_lexical_query()` only expands terms actually present in the question (§12: "Do
not blindly expand every token") -- it appends the OTHER known synonyms for whatever
canonical term(s) were mentioned, as extra keywords for BM25 to match against a document
that happens to use different terminology than the user did (e.g. the user says "profits"
but the filing says "PAT"). The semantic/dense leg doesn't need this -- a good embedding
model already generalizes across financial synonyms reasonably well (see Phase 5's
finding); this is specifically a BM25/lexical-recall aid.
"""
from __future__ import annotations

import re

# canonical -> known synonyms. Deliberately the §12 minimum list, not exhaustive --
# grow it as real query-log gaps are found, per §36 "no untracked optimization."
TERMS: dict[str, list[str]] = {
    "PAT": ["profit after tax", "net profit", "net income"],
    "PBT": ["profit before tax"],
    "EBITDA": ["operating profit before depreciation"],
    "EBIT": ["operating profit"],
    "ROE": ["return on equity"],
    "ROCE": ["return on capital employed"],
    "NPM": ["net profit margin"],
    "YoY": ["year on year", "year over year"],
    "QoQ": ["quarter on quarter", "quarter over quarter"],
    "revenue": ["sales", "turnover", "top line"],
    "operating profit": ["EBIT", "EBITDA"],
}

_WORD_RE_CACHE: dict[str, re.Pattern] = {}


def _word_pattern(term: str) -> re.Pattern:
    pat = _WORD_RE_CACHE.get(term)
    if pat is None:
        pat = re.compile(r"\b" + re.escape(term.lower()) + r"\b")
        _WORD_RE_CACHE[term] = pat
    return pat


def _mentions(text_lower: str, term: str) -> bool:
    return bool(_word_pattern(term).search(text_lower))


def expand_lexical_query(question: str) -> str:
    """Appends every synonym for a term literally mentioned in `question` that isn't
    already present, word-boundary-matched case-insensitively. Returns `question`
    unchanged when no dictionary term is mentioned at all."""
    q_lower = question.lower()
    extra: list[str] = []
    seen = set()
    for canonical, synonyms in TERMS.items():
        forms = [canonical] + synonyms
        if not any(_mentions(q_lower, f) for f in forms):
            continue
        for form in forms:
            key = form.lower()
            if key not in q_lower and key not in seen:
                extra.append(form)
                seen.add(key)
    if not extra:
        return question
    return question + " " + " ".join(extra)


def semantic_query(question: str) -> str:
    """The question as-is -- kept as a named function (not just `lambda q: q`) so a
    future phase can add real semantic rewriting without changing every call site."""
    return question
