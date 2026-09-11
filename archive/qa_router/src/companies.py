from __future__ import annotations

import re

from src import database_ro

STATIC_ALIASES: dict[str, list[str]] = {
    "TCS": ["tata consultancy", "tata consultancy services"],
    "INFY": ["infosys"],
    "HCLTECH": ["hcl tech", "hcl technologies", "hcl"],
    "WIPRO": [],
    "TECHM": ["tech mahindra", "technmahindra"],
    "LTM": ["ltimindtree", "lti mindtree", "lt mindtree"],
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def _candidates(db_path: str) -> dict[str, list[str]]:
    """symbol -> list of alias strings to match against (DB name + the
    symbol itself + static aliases)."""
    candidates: dict[str, list[str]] = {}
    for row in database_ro.list_companies(db_path):
        symbol = row["symbol"]
        aliases = candidates.setdefault(symbol, [symbol])
        if row.get("name"):
            aliases.append(row["name"])
    for symbol, extra in STATIC_ALIASES.items():
        candidates.setdefault(symbol, [symbol]).extend(extra)
    return candidates


def resolve_companies(question: str, db_path: str) -> list[str]:
    normalized_question = _normalize(question)
    candidates = _candidates(db_path)

    raw_matches: list[tuple[int, int, str]] = []  # (start, end, symbol)
    for symbol, aliases in candidates.items():
        for alias in aliases:
            norm_alias = _normalize(alias)
            if not norm_alias:
                continue
            pattern = re.compile(r"\b" + re.escape(norm_alias) + r"\b")
            for m in pattern.finditer(normalized_question):
                raw_matches.append((m.start(), m.end(), symbol))

    raw_matches.sort(key=lambda t: (t[0], -(t[1] - t[0])))
    claimed: list[tuple[int, int]] = []
    ordered_symbols: list[str] = []
    seen: set[str] = set()
    for start, end, symbol in raw_matches:
        if any(not (end <= c[0] or start >= c[1]) for c in claimed):
            continue  # overlaps an already-claimed (and therefore longer, or earlier) span
        claimed.append((start, end))
        if symbol not in seen:
            seen.add(symbol)
            ordered_symbols.append(symbol)

    return ordered_symbols
