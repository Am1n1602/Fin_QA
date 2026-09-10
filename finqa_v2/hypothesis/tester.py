"""HypothesisTester -- the §22 why-question workflow end to end.

detect + quantify -> decompose -> generate candidate causes -> retrieve filing
evidence per cause -> structural check vs the numbers -> classify -> report.

Fully deterministic without an LLM (the LLM, if wired, only phrases extra candidate
causes -- it never classifies). Every structured driver and every retrieved passage
lands in the shared Evidence Workspace so the reasoning layer can cite them.
"""
from __future__ import annotations

import re

from finqa_v2.evidence import EvidenceSet, evidence_from_retrieved_chunk
from finqa_v2.hypothesis.decompose import build_decomposition
from finqa_v2.hypothesis.detect import detect_metric_change
from finqa_v2.hypothesis.generate import generate_candidates
from finqa_v2.hypothesis.models import HypothesisReport
from finqa_v2.hypothesis.validate import classify, lexical_overlap, structural_check

_FY_RE = re.compile(r"FY(\d{4})", re.I)


class HypothesisTester:
    def __init__(self, repos, *, engine=None, retriever=None, provider=None,
                 max_hypotheses: int = 6, docs_per_hypothesis: int = 3):
        self._repos = repos
        if engine is None:
            from finqa_v2.engine import FinancialEngine

            engine = FinancialEngine(repos)
        self._engine = engine
        self._retriever = retriever
        self._provider = provider
        self._max = max_hypotheses
        self._docs_per = docs_per_hypothesis

    # ------------------------------------------------------------------ #
    def run(self, question: str, ticker: str, metric: str, *, basis: str = "consolidated",
            workspace=None, use_llm: bool = True) -> HypothesisReport:
        ws = workspace if workspace is not None else EvidenceSet()
        steps = ["detect + quantify the change"]

        change = detect_metric_change(self._engine, ticker, metric, basis=basis, workspace=ws)
        if change is None or change.direction in ("unknown", "flat"):
            reason = ("the change could not be measured" if change is None
                      else f"{metric.replace('_', ' ')} was roughly unchanged "
                           f"({change.from_period} -> {change.to_period})")
            return HypothesisReport(
                question=question, change=change, steps=steps,
                limitations=[f"No material change to explain: {reason}."],
            )

        steps.append("decompose the change into structured drivers")
        view = build_decomposition(self._engine, change, workspace=ws)

        steps.append("generate candidate causes")
        hyps = generate_candidates(view, question,
                                   provider=self._provider if use_llm else None,
                                   max_total=self._max)

        steps.append("retrieve evidence per cause, structural-check, classify")
        fy = _fy_int(change.to_period)
        for h in hyps:
            doc_confs: list[float] = []
            for hit in self._search(ticker, metric, h.statement, fy):
                ev = evidence_from_retrieved_chunk(hit, repos=self._repos, company=ticker, workspace=ws)
                if lexical_overlap(f"{metric} {h.statement}", ev.text) >= 1:
                    h.doc_evidence_ids.append(ev.evidence_id)
                    doc_confs.append(ev.confidence)
            h.structural_check, h.structural_note = structural_check(h, view)
            h.status, h.confidence = classify(h, doc_confs)
            h.support_evidence_ids = _dedup(
                ([change.evidence_id] if change.evidence_id else [])
                + _signal_evidence(view, h)
                + h.doc_evidence_ids
            )

        limitations: list[str] = []
        if self._retriever is None:
            limitations.append("No document retriever wired: candidate causes were tested against "
                               "the financial numbers only, not against management commentary.")
        elif not any(h.doc_evidence_ids for h in hyps):
            limitations.append("No filing passages matched the candidate causes, so narrative "
                               "confirmation is unavailable in the current corpus.")

        return HypothesisReport(
            question=question, change=change, hypotheses=hyps,
            decomposition=view.summary(), steps=steps, limitations=limitations,
        )

    # ------------------------------------------------------------------ #
    def _search(self, ticker: str, metric: str, statement: str, fy: int | None):
        if self._retriever is None:
            return []
        co = self._repos.companies.resolve(ticker)
        filters: dict = {}
        if co is not None:
            filters["company_id"] = co.company_id
        try:
            return self._retriever.retrieve(f"{metric} {statement}", k=self._docs_per,
                                            filters=filters or None)
        except Exception:
            return []


def _signal_evidence(view, hyp) -> list[str]:
    if not hyp.signal:
        return []
    kind, key = hyp.signal
    got = view.evidence.get(f"{kind}:{key}") or view.evidence.get(kind)
    if got is None:
        return []
    return got if isinstance(got, list) else [got]


def _dedup(xs) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def _fy_int(label: str | None) -> int | None:
    m = _FY_RE.fullmatch((label or "").strip())
    return int(m.group(1)) if m else None
