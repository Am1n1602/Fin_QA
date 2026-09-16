"""§25 checks: calculation re-execution, citation / support, answer-number reconciliation.

Every check is deterministic and independent of the reasoning LLM -- it only trusts the
Evidence Workspace and the pinned calculation inputs.
"""
from __future__ import annotations

import re

from finqa_v2.engine.calculator import calculate
from finqa_v2.evidence.models import EvidenceType
from finqa_v2.verification.models import ClaimCheck

# ------------------------------------------------------------------ #
# calculation re-execution
# ------------------------------------------------------------------ #

def check_calculation(calc: dict) -> ClaimCheck:
    cid, kind, name = calc.get("calculation_id", "?"), calc.get("kind"), calc.get("name", "?")
    result, expr = calc.get("result"), calc.get("expression")
    inputs = calc.get("inputs") or []
    tgt = f"calc:{cid}"
    if result is None:
        return ClaimCheck(tgt, "calculation", "skipped", f"{name}: no result to check")

    if kind in ("growth", "cagr") and len(inputs) == 2:
        a, b = inputs[0].get("value"), inputs[1].get("value")
        if a in (None, 0) or b is None:
            return ClaimCheck(tgt, "calculation", "not_recomputable", f"{name}: missing endpoint values")
        recomputed = (b - a) / a * 100.0 if kind == "growth" else None
        if recomputed is None:
            return ClaimCheck(tgt, "calculation", "not_recomputable", f"{name}: CAGR needs the period span")
        return _cmp(tgt, name, recomputed, result, "%")

    if expr and inputs:
        vars_ = {i["name"]: i["value"] for i in inputs if i.get("value") is not None}
        names = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", expr)) - {"abs", "min", "max", "round"}
        if not names.issubset(vars_):
            return ClaimCheck(tgt, "calculation", "not_recomputable",
                              f"{name}: {sorted(names - set(vars_))} not among the pinned inputs")
        try:
            recomputed = calculate(expr, **vars_)
        except ValueError as e:
            return ClaimCheck(tgt, "calculation", "not_recomputable", f"{name}: {e}")
        return _cmp(tgt, name, recomputed, result, calc.get("unit") or "")

    return ClaimCheck(tgt, "calculation", "not_recomputable", f"{name}: no re-runnable expression")


def _cmp(tgt, name, recomputed, result, unit) -> ClaimCheck:
    tol = max(0.01, abs(result) * 1e-4)
    if abs(recomputed - result) <= tol:
        return ClaimCheck(tgt, "calculation", "recomputed",
                          f"{name} = {result:g}{unit} reproduced from its inputs")
    return ClaimCheck(tgt, "calculation", "does_not_recompute",
                      f"{name}: stored {result:g}{unit}, recomputed {recomputed:g}{unit}")


# ------------------------------------------------------------------ #
# citation + support
# ------------------------------------------------------------------ #

def check_claim(claim: dict, evidence_by_id: dict) -> list[ClaimCheck]:
    cid = claim.get("claim_id", "?")
    tgt = f"claim:{cid}"
    text = (claim.get("text") or "")[:100]
    ev_ids = claim.get("evidence_ids") or []
    calc_ids = claim.get("calculation_ids") or []
    out: list[ClaimCheck] = []

    if not ev_ids and not calc_ids:
        out.append(ClaimCheck(tgt, "support", "unsupported", "claim cites no evidence", text))
        return out
    out.append(ClaimCheck(tgt, "support", "supported", "", text))

    missing = [i for i in ev_ids if i not in evidence_by_id]
    if missing:
        out.append(ClaimCheck(tgt, "citation", "citation_missing",
                              f"evidence_id(s) not in workspace: {missing}", text))
        return out
    if ev_ids:
        out.append(ClaimCheck(tgt, "citation", "cited", "", text))
    # a doc-cited qualitative/causal claim should share wording with the passage
    if claim.get("kind") in ("causal", "qualitative", "cross_validation", "comparative"):
        docs = [evidence_by_id[i] for i in ev_ids
                if evidence_by_id[i].get("type") == EvidenceType.DOCUMENT.value]
        if docs and not any(_overlap(text, d.get("text") or "") for d in docs):
            out.append(ClaimCheck(tgt, "citation", "citation_weak",
                                  "claim wording does not overlap its cited passage", text))
    return out


_STOP = frozenset("the a an of to in for on at by is are was were be has have and or as it "
                  "its this that with from into not no growth change driven segment".split())


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(t) > 2 and t not in _STOP}


def _overlap(a: str, b: str, n: int = 2) -> bool:
    return len(_tokens(a) & _tokens(b)) >= n


# ------------------------------------------------------------------ #
# answer numbers vs the workspace
# ------------------------------------------------------------------ #

_METRIC_WORDS: dict[str, tuple[str, ...]] = {
    "revenue": ("revenue", "sales", "turnover", "topline", "top line"),
    "net_profit": ("net profit", "pat", "profit after tax", "bottom line", "net income"),
    "ebitda": ("ebitda",),
    "ebit": ("ebit", "operating profit"),
    "roe": ("roe", "return on equity"),
    "roa": ("roa", "return on assets"),
    "roce": ("roce", "return on capital"),
    "ebitda_margin": ("ebitda margin",),
    "ebit_margin": ("ebit margin", "operating margin"),
    "net_profit_margin": ("net profit margin", "net margin", "profit margin"),
    "debt_to_equity": ("debt to equity", "debt-to-equity", "d/e", "leverage"),
    "interest_coverage": ("interest coverage",),
    "current_ratio": ("current ratio",),
    "asset_turnover": ("asset turnover",),
    "effective_tax_rate": ("effective tax rate", "tax rate"),
}
_PCT = re.compile(r"(-?\d[\d,]*\.?\d*)\s*(%|pct|per ?cent|percent|pp\b|ppt|percentage points?)")
_X = re.compile(r"(-?\d[\d,]*\.?\d*)\s*(x|times)\b")
_BARE = re.compile(r"(-?\d[\d,]{2,}\.?\d*)")
_INR = re.compile(r"(?:₹|rs\.?|inr)?\s*(-?\d[\d,]*\.?\d*)\s*"
                  r"(lakh crore|l\s*cr|lakh cr|crore|cr|bn|billion|mn|million)\b", re.I)
_SCALE = {"lakh crore": 1e12, "l cr": 1e12, "lakh cr": 1e12, "crore": 1e7, "cr": 1e7,
          "bn": 1e9, "billion": 1e9, "mn": 1e6, "million": 1e6}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text or "")


def _canonical_metric(metric: str | None) -> str | None:
    if not metric:
        return None
    m = re.sub(r"_(yoy|qoq|cagr)$", "", metric)
    return m if m in _METRIC_WORDS else None


_FY = re.compile(r"fy\s?(\d{4})", re.I)


def check_answer_numbers(answer: str, workspace) -> list[ClaimCheck]:
    """Cross-check every figure the answer states against a matching workspace value.

    A sentence is only used for an evidence item when their periods do not conflict --
    an FY in the sentence must equal the evidence's FY (or one end of its range).
    """
    out: list[ClaimCheck] = []
    facts = [e for e in workspace if e.type in (
        EvidenceType.RATIO, EvidenceType.GROWTH, EvidenceType.FINANCIAL_FACT,
        EvidenceType.CALCULATION) and e.value is not None]
    if not facts:
        return out
    sents = _sentences(answer)
    seen: set[tuple] = set()

    for e in facts:
        cm = _canonical_metric(e.metric)
        if cm is None:
            continue
        key = (e.company, cm, e.period)
        if key in seen:
            continue
        ev_fys = set(_FY.findall(e.period or ""))
        words = _METRIC_WORDS[cm]
        for sent in sents:
            low = sent.lower()
            if not any(w in low for w in words):
                continue
            sent_fys = set(_FY.findall(low))
            if sent_fys and ev_fys and not (sent_fys & ev_fys):
                continue                       # the sentence is about a different period
            if sent_fys and not ev_fys and len(sent_fys) == 1:
                continue                       # dated sentence, undated evidence -> don't guess
            claimed, fam = _claimed_value(low, e.unit, e.value)
            if claimed is None:
                continue
            verdict, detail = _reconcile(claimed, fam, e)
            if verdict == "mismatch" and _ambiguous(low, e.unit):
                verdict, detail = "unverifiable", detail + " (multiple figures in the sentence)"
            tag = " ".join(x for x in (e.company or "?", e.metric, e.period or "") if x)
            out.append(ClaimCheck("answer", "numeric", verdict, f"{detail} [{tag}]",
                                  sent.strip()[:120]))
            seen.add(key)
            break
    return out


def _claimed_value(sentence: str, unit: str | None, ref: float | None = None):
    """-> (value, family) where family in {'pct','x','inr'} or (None, None)."""
    sentence = _FY.sub(" ", sentence)                  # drop 'FY2026' so a year is never a figure
    if unit in ("pct", "pp"):
        m = _PCT.search(sentence)
        return (_num(m.group(1)), "pct") if m else (None, None)
    if unit == "x":
        m = _X.search(sentence)
        return (_num(m.group(1)), "x") if m else (None, None)
    if unit == "INR":
        m = _INR.search(sentence)
        if m:
            v = _num(m.group(1)) * _SCALE[re.sub(r"\s+", " ", m.group(2).lower())]
            return (v, "inr")
        if ref:                                       # bare grouped number, magnitude-sanity-checked
            for tok in _BARE.findall(sentence):
                if "," not in tok:
                    continue
                v = _num(tok)
                if 0.01 <= abs(v) / abs(ref) <= 100:
                    return (v, "inr")
        return (None, None)
    return (None, None)


def _ambiguous(sentence: str, unit: str | None) -> bool:
    s = _FY.sub(" ", sentence)
    if unit in ("pct", "pp"):
        return len(_PCT.findall(s)) > 1
    if unit == "x":
        return len(_X.findall(s)) > 1
    if unit == "INR":
        return len(_INR.findall(s)) + sum("," in t for t in _BARE.findall(s)) > 1
    return False


def _reconcile(claimed: float, fam: str, e) -> tuple[str, str]:
    actual = e.value
    if fam in ("pct", "x"):
        tol = max(0.5, abs(actual) * 0.02)
    else:                                   # inr
        tol = max(abs(actual) * 0.03, 1.0)
    if abs(claimed - actual) <= tol:
        return "confirmed", f"answer states {claimed:g}, evidence has {actual:g}"
    return "mismatch", f"answer states {claimed:g}, evidence has {actual:g}"
