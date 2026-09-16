"""Answer-quality scoring (§39): groundedness, citation precision/recall, correctness. See docs/file-guide.md."""
from __future__ import annotations

from typing import Any

from evaluation.evaluators.numerical import NumericalEvaluator


def _response(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result, dict) and isinstance(result.get("response"), dict):
        return result["response"]
    return result if isinstance(result, dict) else {}


class GroundednessEvaluator:
    """A claim is grounded when every evidence_id it cites is in the workspace and the
    verifier did not flag its citation as missing/unsupported."""

    name = "groundedness"

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        resp = _response(result)
        claims = resp.get("claims") or []
        if not claims:
            return {"metrics": {"grounded_rate": None}, "verdict": "na", "detail": "no claims"}
        ws_ids = {e.get("evidence_id") for e in (resp.get("evidence") or [])}
        calc_ids = {c.get("calculation_id") for c in (resp.get("calculations") or [])}
        checks = ((result or {}).get("verification") or {}).get("checks") or []
        bad_claim_texts = {c.get("text") for c in checks
                           if c.get("kind") in ("citation", "support")
                           and c.get("verdict") in ("citation_missing", "unsupported")}
        grounded = 0
        for c in claims:
            ev = list(c.get("evidence_ids") or [])
            ca = list(c.get("calculation_ids") or [])
            ids_ok = bool(ev or ca) and all(i in ws_ids for i in ev) and all(i in calc_ids for i in ca)
            if ids_ok and c.get("text") not in bad_claim_texts:
                grounded += 1
        rate = grounded / len(claims)
        return {
            "metrics": {"n_claims": len(claims), "grounded_claims": grounded,
                        "grounded_rate": round(rate, 4)},
            "verdict": "pass" if grounded == len(claims) else ("fail" if rate < 0.5 else "warn"),
            "detail": f"{grounded}/{len(claims)} claims fully grounded in the workspace",
        }


def _src_matches(ref: dict[str, Any], got: dict[str, Any]) -> bool:
    r_sec = (ref.get("section") or "").strip().lower()
    g_sec = (got.get("section") or "").strip().lower()
    if r_sec and g_sec and not (r_sec in g_sec or g_sec in r_sec):
        return False
    r_doc = (ref.get("document") or "").strip().lower()
    g_title = (got.get("title") or "").strip().lower()
    if r_doc and g_title and not any(tok in g_title for tok in r_doc.split() if len(tok) > 3):
        # allow section-only matches; only reject when a doc name was given and clearly differs
        if r_sec and g_sec:
            pass
        else:
            return False
    r_page = ref.get("page")
    g_page, g_end = got.get("page"), got.get("page_end") or got.get("page")
    if r_page is not None and g_page is not None:
        if not (g_page - 1 <= r_page <= (g_end or g_page) + 1):
            return False
    return True


class CitationEvaluator:
    """Precision/recall of the answer's `sources` against `record.reference_sources`."""

    name = "citation"

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        refs = record.get("reference_sources") or []
        got = _response(result).get("sources") or []
        if not refs:
            return {"metrics": {"precision": None, "recall": None, "n_got": len(got)},
                    "verdict": "na", "detail": "no reference citations"}
        matched_ref = [r for r in refs if any(_src_matches(r, g) for g in got)]
        matched_got = [g for g in got if any(_src_matches(r, g) for r in refs)]
        precision = len(matched_got) / len(got) if got else 0.0
        recall = len(matched_ref) / len(refs)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        return {
            "metrics": {"precision": round(precision, 4), "recall": round(recall, 4),
                        "f1": round(f1, 4), "n_got": len(got), "n_ref": len(refs)},
            "verdict": "pass" if recall >= 0.5 and precision >= 0.5 else "fail",
            "detail": f"matched {len(matched_ref)}/{len(refs)} reference sources",
        }


class CorrectnessEvaluator:
    """Numeric -> tolerance match; text -> keyword coverage of `must_contain`.
    LLM-judged semantic correctness is deferred (Phase 19/20)."""

    name = "correctness"

    def __init__(self) -> None:
        self._num = NumericalEvaluator()

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        if record.get("answer_type") == "numeric" and record.get("reference_value") is not None:
            s = self._num.score(record, result)
            return {"metrics": {"mode": "numeric", **s["metrics"]},
                    "verdict": s["verdict"], "detail": s["detail"]}
        must = [w.lower() for w in (record.get("must_contain") or [])]
        if not must:
            return {"metrics": {"mode": "none"}, "verdict": "na",
                    "detail": "no reference_value or must_contain to check"}
        answer = (_response(result).get("answer") or "").lower()
        hits = [w for w in must if w in answer]
        cov = len(hits) / len(must)
        return {
            "metrics": {"mode": "keyword", "coverage": round(cov, 4),
                        "hits": hits, "missing": [w for w in must if w not in answer]},
            "verdict": "pass" if cov >= 0.6 else "fail",
            "detail": f"{len(hits)}/{len(must)} required phrases present",
        }
