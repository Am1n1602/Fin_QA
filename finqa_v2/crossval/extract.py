"""§23 step 1: pull the checkable management claim out of the question.

Deterministic regex extraction; an optional LLM pass only backfills the assertion text
and a mechanism when the rules find none. Never invents a subject or a direction.
"""
from __future__ import annotations

import re

from finqa_v2.crossval.models import ManagementClaim
from finqa_v2.llm import LLMBudgetExceededError, LLMError, NullProvider

# ---- claim span -------------------------------------------------------------
_ATTRIB = re.compile(
    r"management\s+(?:has\s+)?(?:said|says|claimed|claims|highlighted|attributed|noted|"
    r"indicated|stated|commented|guided|expects?)\s+(?:that\s+|it\s+|to\s+)?(.+?)"
    r"(?:[.?]|$)", re.I)
_DRIVEN = re.compile(r"([^.?]*\b(?:driven by|drove|led by|on account of|attributable to|"
                     r"because of|due to|thanks to)\b[^.?]*)", re.I)
_TRAILER = re.compile(
    r"\s*(?:[-–—]\s*)?(?:is|are|do|does|did)?\s*(?:this|that|it)?\s*"
    r"(?:visible|supported|reflected|consistent|borne out|confirmed|true)\b.*$", re.I)
_LEAD = re.compile(r"^\s*(?:so\s+|and\s+|but\s+)?(?:is it true that|do the financials show that"
                   r"|check (?:whether|if)|verify (?:that|whether))\s+", re.I)
# a claim span is only accepted from the loose fallback if the question is framed as a
# verification of an assertion (not a plain "what was X?" lookup)
_VERIFY_FRAME = re.compile(
    r"\b(management|driven by|drove|led by|attributed|on account of|because of|due to|"
    r"supported|consistent with|visible in|borne out|reflected in|confirmed by|"
    r"do the (?:reported )?financ|does the data)\b", re.I)

# ---- subject (canonical metric) -------------------------------------------
_SUBJECT_PHRASES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bebitda margin\b"), "ebitda_margin"),
    (re.compile(r"\boperating margin\b|\bebit margin\b|\boperating leverage\b"), "ebit_margin"),
    (re.compile(r"\bgross margin\b"), "ebit_margin"),
    (re.compile(r"\bnet (?:profit )?margin\b|\bprofitability\b|\bmargins?\b"), "net_profit_margin"),
    (re.compile(r"\bebitda\b"), "ebitda"),
    (re.compile(r"\b(?:net profit|pat|profit after tax|bottom[ -]?line|earnings)\b"), "net_profit"),
    (re.compile(r"\b(?:revenue|sales|top[ -]?line|turnover|growth)\b"), "revenue"),
]

_UP = re.compile(r"\b(expansion|expanded|expand|improv\w*|higher|rose|grew|grow\w*|increas\w*|"
                 r"gain\w*|strong\w*|accelerat\w*|up|widen\w*|beat)\b", re.I)
_DOWN = re.compile(r"\b(contraction|contract\w*|declin\w*|lower|fell|fall\w*|decreas\w*|weak\w*|"
                   r"compress\w*|drop\w*|down|shrank|shrink\w*|miss\w*|drag\w*)\b", re.I)

_MECH: list[tuple[re.Pattern, tuple[str, str]]] = [
    (re.compile(r"\b(volume growth|higher volumes?|volumes?)\b", re.I), ("volume", "volume_pricing")),
    (re.compile(r"\b(pricing|price (?:hikes?|increases?|realisation|realization)|realis\w*|"
                r"billing rate|rate hike)\b", re.I), ("pricing", "volume_pricing")),
    (re.compile(r"\b(demand|order book|order[- ]?inflow|bookings|deal wins|tcv|new deals)\b", re.I),
     ("demand", "demand")),
    (re.compile(r"\b(cost (?:control|discipline|reduction|optimi[sz]ation|efficienc\w*|takeout)|"
                r"operating leverage|productivity|automation|lower costs?)\b", re.I),
     ("cost_control", "cost")),
    (re.compile(r"\b(mix|premiumi[sz]ation|richer mix|portfolio mix|product mix)\b", re.I),
     ("mix", "mix")),
    (re.compile(r"\b(acqui\w*|inorganic|merger|integration of)\b", re.I), ("acquisition", "generic")),
]

_SEGMENT_PHRASE = re.compile(
    r"\b(?:by|from|to|in|led by|driven by|attributed to|within)\s+"
    r"(?:the\s+|its\s+|strong\s+|robust\s+|higher\s+)?"
    r"([A-Za-z][\w&/ ]*?)\s+(?:segment|business|vertical|division|portfolio)\b", re.I)

_VALUE = re.compile(r"(\d+(?:\.\d+)?)\s*(%|per ?cent|percent|bps|basis points|pp|ppt|"
                    r"percentage points?|crores?|cr\b)", re.I)
_FY = re.compile(r"\bFY\s?'?(\d{2}(?:\d{2})?)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" .,-–—")


def _claim_span(text: str) -> str | None:
    m = _ATTRIB.search(text)
    if m:
        return _norm(m.group(1))
    m = _DRIVEN.search(text)
    if m:
        return _norm(_TRAILER.sub("", m.group(1)))
    # loose fallback -- only when the question is framed as verifying an assertion
    if not _VERIFY_FRAME.search(text):
        return None
    stripped = _norm(_TRAILER.sub("", _LEAD.sub("", text)))
    return stripped or None


def _subject(text: str) -> str | None:
    for pat, name in _SUBJECT_PHRASES:
        if pat.search(text):
            return name
    return None


def _mechanism(text: str) -> tuple[str | None, str]:
    seg = _SEGMENT_PHRASE.search(text)
    if seg:
        name = _norm(seg.group(1))
        if name and name.lower() not in ("revenue", "overall", "core", "total"):
            return name, "segment"
    for pat, (mech, kind) in _MECH:
        if pat.search(text):
            return mech, kind
    return None, "generic"


def _value(text: str) -> tuple[float | None, str | None]:
    m = _VALUE.search(text)
    if not m:
        return None, None
    v = float(m.group(1))
    u = m.group(2).lower()
    if u.startswith("bps") or u.startswith("basis"):
        return v / 100.0, "pp"
    if u in ("pp", "ppt") or u.startswith("percentage point"):
        return v, "pp"
    if u.startswith("cr"):
        return v, "INR"
    return v, "pct"


def _direction(text: str, subject: str | None) -> str | None:
    up, down = bool(_UP.search(text)), bool(_DOWN.search(text))
    if up and not down:
        return "increase"
    if down and not up:
        return "decrease"
    return None


def _kind(subject, direction, mechanism, mechanism_kind, value) -> str:
    if mechanism_kind == "segment":
        return "segment_strength"
    if subject and subject.endswith("margin"):
        return "margin_move"
    if mechanism:
        return "growth_driver"
    if value is not None:
        return "magnitude"
    if direction:
        return "directional"
    return "generic"


def extract_claim(text: str, *, plan_metrics=None, provider=None) -> ManagementClaim | None:
    text = (text or "").strip()
    if not text:
        return None
    span = _claim_span(text)
    if not span:
        return None

    subject = _subject(span) or _subject(text)
    if subject is None and plan_metrics:
        subject = plan_metrics[0]
    direction = _direction(span, subject)
    mechanism, mechanism_kind = _mechanism(span)
    value, unit = _value(span)
    fy = _FY.search(text)
    period = None
    if fy:
        yy = fy.group(1)
        period = f"FY{yy if len(yy) == 4 else '20' + yy}"

    origin = "rules"
    if mechanism is None and provider is not None and not isinstance(provider, NullProvider):
        llm = _llm_fill(text, provider)
        if llm:
            origin = "rules+llm"
            mechanism = mechanism or llm.get("mechanism")
            if mechanism and mechanism_kind == "generic":
                mechanism_kind = _classify_mechanism(mechanism)
            subject = subject or llm.get("subject")
            direction = direction or llm.get("direction")

    kind = _kind(subject, direction, mechanism, mechanism_kind, value)
    return ManagementClaim(
        raw=span, kind=kind, subject=subject, direction=direction,
        mechanism=mechanism, mechanism_kind=mechanism_kind,
        claimed_value=value, claimed_unit=unit, period=period, origin=origin,
    )


_MECH_WORDS = {
    "volume_pricing": ("volume", "price", "pricing", "realis"),
    "demand": ("demand", "order", "booking", "deal"),
    "cost": ("cost", "efficien", "productivity", "leverage"),
    "mix": ("mix", "premium"),
}


def _classify_mechanism(mechanism: str) -> str:
    m = mechanism.lower()
    for kind, words in _MECH_WORDS.items():
        if any(w in m for w in words):
            return kind
    return "generic"


_LLM_JSON = re.compile(r"\{.*\}", re.S)
_LLM_SYSTEM = ("Extract the factual assertion a company's management is making. Return JSON "
               "only; use null for anything not explicitly stated. Do not guess numbers.")


def _llm_fill(text: str, provider) -> dict | None:
    prompt = (f'Question: {text}\n\n'
              'Return {"assertion": "...", "subject": "revenue|net_profit|margin|null", '
              '"direction": "increase|decrease|null", "mechanism": "short phrase or null"}')
    try:
        raw = provider.complete(prompt, system=_LLM_SYSTEM, json_object=True,
                                temperature=0.0, max_tokens=180)
    except (LLMError, LLMBudgetExceededError):
        return None
    import json

    m = _LLM_JSON.search(raw or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict):
        return None
    out = {}
    subj = str(d.get("subject") or "").lower()
    if "margin" in subj:
        out["subject"] = "net_profit_margin"
    elif subj in ("revenue", "net_profit"):
        out["subject"] = subj
    if d.get("direction") in ("increase", "decrease"):
        out["direction"] = d["direction"]
    mech = d.get("mechanism")
    if isinstance(mech, str) and 2 <= len(mech) <= 60:
        out["mechanism"] = _norm(mech)
    return out or None
