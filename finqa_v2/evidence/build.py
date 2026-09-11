"""Adapters: engine / retrieval / segment output -> standardized Evidence (+ Calculation).

Nothing here calls an LLM. These are the only sanctioned way for raw results to enter
the Evidence Workspace.
"""
from __future__ import annotations

import re
import uuid

from finqa_v2.evidence.confidence import (
    document_confidence,
    evidence_confidence_for_type,
)
from finqa_v2.evidence.models import Calculation, Citation, Evidence, EvidenceType
from finqa_v2.normalize.units import unit_for

_KIND_TO_TYPE = {
    "metric": EvidenceType.FINANCIAL_FACT,
    "ratio": EvidenceType.RATIO,
    "valuation": EvidenceType.RATIO,
    "growth": EvidenceType.GROWTH,
    "cagr": EvidenceType.GROWTH,
    "comparison": EvidenceType.CALCULATION,
    "decomposition": EvidenceType.CALCULATION,
    "calculation": EvidenceType.CALCULATION,
}
_FLAG_RE = re.compile(r"^([a-z_]+): source record flagged", re.I)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _flagged_metrics(limitations) -> set[str]:
    out = set()
    for lim in limitations or ():
        m = _FLAG_RE.match(lim)
        if m:
            out.add(m.group(1))
    return out


# --------------------------------------------------------------------------- #
# Financial Engine
# --------------------------------------------------------------------------- #

def evidence_from_engine_result(res, *, workspace=None, id_prefix: str = "eng"):
    """-> (result_evidence, calculation). Sub-evidence for each input fact is added to
    the workspace (if given) and referenced from both the calculation and the result."""
    flagged = _flagged_metrics(getattr(res, "limitations", ()))
    sub_ids: list[str] = []
    calc_inputs: list[dict] = []
    for fr in getattr(res, "inputs", ()):
        u = unit_for(fr.metric)
        ev = Evidence(
            evidence_id=_id(f"{id_prefix}-in"),
            type=EvidenceType.FINANCIAL_FACT,
            text=f"{res.company} {fr.metric} ({fr.period}) = {fr.value} {u or ''}".strip(),
            company=res.company, metric=fr.metric, period=fr.period,
            value=fr.value, unit=u,
            confidence=evidence_confidence_for_type(
                EvidenceType.FINANCIAL_FACT, review_flagged=fr.metric in flagged),
        )
        if workspace is not None:
            sub_ids.append(workspace.add(ev))
        else:
            sub_ids.append(ev.evidence_id)
        calc_inputs.append({"name": fr.metric, "value": fr.value, "unit": u,
                            "evidence_id": sub_ids[-1]})

    calc = Calculation(
        calculation_id=_id(f"{id_prefix}-calc"),
        kind=res.kind, name=res.name, result=res.value, unit=res.unit,
        expression=res.formula, inputs=tuple(calc_inputs), period=res.period,
        limitations=tuple(getattr(res, "limitations", ())),
    )
    ev_type = _KIND_TO_TYPE.get(res.kind, EvidenceType.CALCULATION)
    derived = res.kind == "metric" and res.formula is not None
    result_ev = Evidence(
        evidence_id=_id(id_prefix),
        type=ev_type,
        text=f"{res.company} {res.name} ({res.period}) = {res.value} {res.unit or ''}".strip(),
        company=res.company, metric=res.name, period=res.period,
        value=res.value, unit=res.unit, formula=res.formula,
        inputs=tuple(sub_ids),
        confidence=evidence_confidence_for_type(
            ev_type, derived=derived, review_flagged=bool(flagged)),
        limitations=tuple(getattr(res, "limitations", ())),
    )
    if workspace is not None:
        workspace.add(result_ev)
    return result_ev, calc


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #

def citation_for_document(repos, document_id: int, *, page=None, page_end=None,
                          section=None) -> Citation:
    doc = repos.documents.get(document_id)
    src = repos.sources.get(doc.source_id) if (doc and doc.source_id) else None
    company = repos.companies.get(doc.company_id) if doc else None
    return Citation(
        citation_id=f"cite-doc{document_id}",
        kind="document",
        title=doc.title if doc else None,
        company=company.ticker if company else None,
        document_id=document_id, page=page, page_end=page_end, section=section,
        uri=src.uri if src else None,
        period=(doc.period_label if doc else None),
        source_id=(doc.source_id if doc else None),
    )


def evidence_from_retrieved_chunk(hit, *, repos=None, company: str | None = None,
                                  workspace=None) -> Evidence:
    ch = hit.chunk
    cite = None
    if repos is not None and ch.document_id is not None:
        cite = citation_for_document(repos, ch.document_id, page=ch.page_start,
                                     page_end=ch.page_end, section=ch.section)
        company = company or (cite.company)
    score = hit.scores.get("rerank") or hit.scores.get("rrf") or hit.scores.get("lexical")
    ev = Evidence(
        evidence_id=_id("doc"),
        type=EvidenceType.DOCUMENT,
        text=ch.text, company=company, company_id=ch.company_id,
        document_id=ch.document_id, page=ch.page_start, section=ch.section,
        period=(f"FY{ch.financial_year}" if ch.financial_year else None),
        retrieval_score=score,
        confidence=document_confidence(
            rerank_score=hit.scores.get("rerank"),
            rrf_score=hit.scores.get("rrf"),
            bm25_score=hit.scores.get("lexical"),
            rank=hit.rank,
        ),
        citation=cite,
    )
    if workspace is not None:
        workspace.add(ev)
    return ev


# --------------------------------------------------------------------------- #
# Company comparison / ranking
# --------------------------------------------------------------------------- #

def evidence_from_compare_result(res: dict, *, workspace=None) -> list[Evidence]:
    """Adapter for FinancialEngine.compare_companies' return dict -- a ranking across
    several tickers, not a single EngineResult, so evidence_from_engine_result doesn't
    apply. Without this, a comparison/ranking answer had NO evidence at all (the tool
    registration used to hand back an empty evidence list), so the deterministic
    synthesizer and the LLM prompt both had nothing to cite and silently fell back to
    whatever other single-company tool happened to also be planned."""
    out: list[Evidence] = []
    ev_type = EvidenceType.COMPARISON
    metric_label = (res.get("metric") or "").replace("_", " ")
    unit = res.get("unit")
    for row in res.get("results", []):
        period = row.get("period") or res.get("period")
        text = (f"{row['ticker']} ranked #{row['rank']} on {metric_label}: "
                f"{row['value']}" + (f" {unit}" if unit else ""))
        ev = Evidence(
            evidence_id=_id("cmp"),
            type=ev_type,
            text=text, company=row["ticker"], metric=res.get("metric"),
            period=period, value=row["value"], unit=unit,
            confidence=evidence_confidence_for_type(ev_type),
        )
        out.append(ev)
        if workspace is not None:
            workspace.add(ev)
    return out


# --------------------------------------------------------------------------- #
# Segments
# --------------------------------------------------------------------------- #

def evidence_from_segment_result(res, *, workspace=None) -> list[Evidence]:
    out: list[Evidence] = []
    for row in res.rows:
        company = f"{res.company} " if res.company else ""
        if hasattr(row, "contribution_pct"):          # SegmentRow (level)
            text = (f"{company}{row.segment}: revenue {row.revenue:,.0f} INR"
                    + (f", {row.contribution_pct:.1f}% of total" if row.contribution_pct is not None else ""))
            value = row.revenue
        else:                                          # SegmentGrowthRow (change)
            share = (f", {row.share_of_total_change_pct:+.0f}% of the total change"
                     if row.share_of_total_change_pct is not None else "")
            gp = f" ({row.growth_pct:+.1f}%)" if row.growth_pct is not None else ""
            text = f"{company}{row.segment}: revenue change {row.abs_change:+,.0f} INR{gp}{share}"
            value = row.abs_change
        ev = Evidence(
            evidence_id=_id("seg"),
            type=EvidenceType.SEGMENT,
            text=text, company=res.company, metric="segment_revenue",
            period=res.period, value=value, unit="INR",
            confidence=evidence_confidence_for_type(EvidenceType.SEGMENT),
            limitations=tuple(getattr(res, "limitations", ())),
        )
        out.append(ev)
        if workspace is not None:
            workspace.add(ev)
    return out
