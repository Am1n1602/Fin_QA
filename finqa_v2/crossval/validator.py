"""CrossValidator -- the §23 workflow end to end.

extract the management claim -> structured checks vs financials + segment data ->
corroborate against filing text -> adjudicate into one ClaimStatus.

Deterministic without an LLM or retriever (the LLM only helps parse a mechanism; the
retriever only adds the "did management actually say it" step). Every check and passage
lands in the shared Evidence Workspace.
"""
from __future__ import annotations

import re

from finqa_v2.crossval.adjudicate import adjudicate
from finqa_v2.crossval.checks import run_structured_checks
from finqa_v2.crossval.corroborate import corroborate_in_docs
from finqa_v2.crossval.extract import extract_claim
from finqa_v2.crossval.models import CrossValidationReport
from finqa_v2.evidence import EvidenceSet

_FY_RE = re.compile(r"FY(\d{4})", re.I)


class CrossValidator:
    def __init__(self, repos, *, engine=None, retriever=None, provider=None, docs_k=6):
        self._repos = repos
        if engine is None:
            from finqa_v2.engine import FinancialEngine

            engine = FinancialEngine(repos)
        self._engine = engine
        self._retriever = retriever
        self._provider = provider
        self._docs_k = docs_k

    def validate(self, question, ticker, *, statement=None, plan_metrics=None,
                 basis="consolidated", workspace=None, use_llm=True) -> CrossValidationReport:
        ws = workspace if workspace is not None else EvidenceSet()
        steps = ["extract the management claim"]

        claim = extract_claim(statement or question, plan_metrics=plan_metrics,
                              provider=self._provider if use_llm else None)
        if claim is None:
            return CrossValidationReport(
                question=question, company=ticker, claim=None, steps=steps,
                limitations=["Could not identify a checkable management claim in the question."],
            )

        steps.append("run structured checks against the financials + segment data")
        checks, view, change = run_structured_checks(self._engine, ticker, claim,
                                                     basis=basis, workspace=ws)

        steps.append("corroborate against filing text")
        fy = _fy_int(claim.period) or _fy_int(getattr(change, "to_period", None))
        doc_status, doc_ids = corroborate_in_docs(self._retriever, self._repos, ticker, claim,
                                                  fy, workspace=ws, k=self._docs_k)

        steps.append("adjudicate")
        status, conf, lims = adjudicate(claim, checks, doc_status)
        if self._retriever is None:
            lims.append("No document retriever wired: the claim was checked against the "
                        "financial numbers only, not against the filing narrative.")

        support = _dedup(
            [eid for c in checks for eid in c.evidence_ids]
            + ([change.evidence_id] if change is not None and change.evidence_id else [])
            + doc_ids
        )
        return CrossValidationReport(
            question=question, company=ticker, claim=claim, checks=checks,
            doc_status=doc_status, doc_evidence_ids=doc_ids, status=status,
            confidence=conf, steps=steps, limitations=lims, support_evidence_ids=support,
        )


def _dedup(xs) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def _fy_int(label) -> int | None:
    m = _FY_RE.fullmatch((label or "").strip()) if isinstance(label, str) else None
    return int(m.group(1)) if m else None
