"""EvidenceSet -- the Evidence Workspace (§21). An ordered, deduped collection the
reasoning layer reads instead of touching the database."""
from __future__ import annotations

from dataclasses import replace

from finqa_v2.evidence.models import Evidence, EvidenceType


def _dedup_key(ev: Evidence):
    if ev.type is EvidenceType.DOCUMENT:
        return ("doc", ev.document_id, ev.page, (ev.text or "")[:120])
    return (ev.type.value, ev.company_id, ev.metric, ev.period, ev.value)


class EvidenceSet:
    def __init__(self):
        self._items: list[Evidence] = []
        self._by_id: dict[str, Evidence] = {}
        self._seen: set = set()

    # ------------------------------------------------------------------ #
    def add(self, ev: Evidence) -> str:
        key = _dedup_key(ev)
        if key in self._seen:
            # keep the higher-confidence copy, but under the id already handed out for
            # this slot -- callers hold that id, and a later replacement must not orphan it
            for i, cur in enumerate(self._items):
                if _dedup_key(cur) == key:
                    if ev.confidence > cur.confidence:
                        merged = ev if ev.evidence_id == cur.evidence_id else \
                            replace(ev, evidence_id=cur.evidence_id)
                        self._items[i] = merged
                        self._by_id[cur.evidence_id] = merged
                    return self._items[i].evidence_id
        self._seen.add(key)
        self._items.append(ev)
        self._by_id[ev.evidence_id] = ev
        return ev.evidence_id

    def extend(self, evs) -> list[str]:
        return [self.add(e) for e in evs]

    # ------------------------------------------------------------------ #
    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)

    def by_type(self, ev_type: EvidenceType | str) -> list[Evidence]:
        t = EvidenceType(ev_type)
        return [e for e in self._items if e.type is t]

    def by_metric(self, metric: str) -> list[Evidence]:
        return [e for e in self._items if e.metric == metric]

    def by_company(self, company_id: int) -> list[Evidence]:
        return [e for e in self._items if e.company_id == company_id]

    def documents(self) -> list[Evidence]:
        return self.by_type(EvidenceType.DOCUMENT)

    def facts(self) -> list[Evidence]:
        return [e for e in self._items if e.type in (
            EvidenceType.FINANCIAL_FACT, EvidenceType.RATIO, EvidenceType.GROWTH,
            EvidenceType.SEGMENT, EvidenceType.CALCULATION)]

    def top(self, n: int, *, ev_type: EvidenceType | str | None = None) -> list[Evidence]:
        pool = self.by_type(ev_type) if ev_type is not None else list(self._items)
        return sorted(
            pool,
            key=lambda e: (e.confidence, e.retrieval_score or 0.0),
            reverse=True,
        )[:n]

    # ------------------------------------------------------------------ #
    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def to_list(self) -> list[dict]:
        return [e.to_dict() for e in self._items]
