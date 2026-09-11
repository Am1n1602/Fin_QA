"""ClaimGraphView -- resolve a ClaimGraph into an explainable, serialisable structure.

`explain(claim)` gives one claim's full provenance subtree (evidence -> source,
calculation -> input evidence -> source) with a confidence breakdown. `to_graph()` gives
the whole thing as typed nodes + edges; `to_mermaid()` renders that for the docs / UI.
No LLM, no new computation -- it only reads what the reasoning layer already assembled.
"""
from __future__ import annotations

import re

from finqa_v2.evidence.confidence import claim_confidence
from finqa_v2.evidence.models import ClaimStatus

_STATUS_FACTOR = {
    ClaimStatus.SUPPORTED: 1.0,
    ClaimStatus.PARTIALLY_SUPPORTED: 0.6,
    ClaimStatus.NOT_SUPPORTED: 0.2,
    ClaimStatus.INSUFFICIENT_EVIDENCE: 0.1,
}
_CALC_SUPPORT = 0.95        # a reproduced deterministic calculation, per confidence.py


def _clip(s, n: int = 160) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()[:n]


def _fmt(v) -> str:
    if v is None:
        return "N/A"
    return f"{v:,.2f}" if isinstance(v, float) else str(v)


class ClaimGraphView:
    def __init__(self, graph):
        self._g = graph
        self._ws = graph.workspace
        self._calcs = {c.calculation_id: c for c in graph.calculations}
        self._sources = {}
        for e in self._ws:
            if e.citation is not None:
                self._sources.setdefault(e.citation.citation_id, e.citation)

    # ------------------------------------------------------------------ #
    # node builders
    # ------------------------------------------------------------------ #
    def _source_node(self, cite) -> dict:
        return {
            "citation_id": cite.citation_id, "kind": cite.kind, "label": cite.label(),
            "title": cite.title, "company": cite.company, "document_id": cite.document_id,
            "page": cite.page, "page_end": cite.page_end, "section": cite.section,
            "uri": cite.uri, "period": cite.period, "source_id": cite.source_id,
        }

    def _ev_node(self, e) -> dict:
        return {
            "evidence_id": e.evidence_id, "type": e.type.value, "text": _clip(e.text),
            "company": e.company, "metric": e.metric, "period": e.period,
            "value": e.value, "unit": e.unit, "confidence": round(e.confidence, 4),
            "derived_from": [i for i in e.inputs if self._ws.get(i)],
            "source": self._source_node(e.citation) if e.citation is not None else None,
        }

    def _calc_node(self, c) -> dict:
        inputs = []
        for i in c.inputs:
            ei = i.get("evidence_id")
            sub = self._ws.get(ei) if ei else None
            inputs.append({"name": i.get("name"), "value": i.get("value"),
                           "unit": i.get("unit"),
                           "evidence": self._ev_node(sub) if sub is not None else None})
        return {
            "calculation_id": c.calculation_id, "name": c.name, "kind": c.kind,
            "result": c.result, "unit": c.unit, "expression": c.expression,
            "period": c.period, "limitations": list(c.limitations), "inputs": inputs,
        }

    # ------------------------------------------------------------------ #
    # claim-level explanation
    # ------------------------------------------------------------------ #
    def _resolve(self, claim):
        if isinstance(claim, str):
            c = self._g.get_claim(claim)
            if c is None:
                raise KeyError(f"no claim {claim!r} in the graph")
            return c
        return claim

    def explain(self, claim) -> dict:
        cl = self._resolve(claim)
        evs = [self._ev_node(self._ws.get(i)) for i in cl.evidence_ids if self._ws.get(i)]
        calcs = [self._calc_node(self._calcs[i]) for i in cl.calculation_ids if i in self._calcs]

        cites: dict[str, object] = {}
        for i in cl.evidence_ids:
            e = self._ws.get(i)
            if e is not None and e.citation is not None:
                cites[e.citation.citation_id] = e.citation
        for c in calcs:
            for inp in c["inputs"]:
                se = inp.get("evidence")
                if se and se.get("source"):
                    sid = se["source"]["citation_id"]
                    if sid in self._sources:
                        cites[sid] = self._sources[sid]

        support = [self._ws.get(i).confidence for i in cl.evidence_ids if self._ws.get(i)]
        support += [_CALC_SUPPORT for i in cl.calculation_ids
                    if i in self._calcs and self._calcs[i].result is not None]
        breakdown = {
            "support_confidences": [round(s, 4) for s in support],
            "mean_support": round(sum(support) / len(support), 4) if support else 0.0,
            "status": cl.status.value,
            "status_factor": _STATUS_FACTOR[cl.status],
            "claim_confidence": round(claim_confidence(support, cl.status), 4),
        }
        return {
            "claim": {
                "claim_id": cl.claim_id, "text": cl.text, "kind": cl.kind,
                "value": cl.value, "unit": cl.unit, "status": cl.status.value,
                "confidence": round(cl.confidence, 4),
            },
            "evidence": evs,
            "calculations": calcs,
            "sources": [self._source_node(c) for c in cites.values()],
            "confidence_breakdown": breakdown,
        }

    def render(self, claim) -> str:
        d = self.explain(claim)
        c = d["claim"]
        out = [f"[{c['status']}] {c['text']}  (confidence {c['confidence']})"]
        for e in d["evidence"]:
            val = f" = {_fmt(e['value'])}{(' ' + e['unit']) if e['unit'] else ''}" if e["value"] is not None else ""
            head = " ".join(x for x in (e["company"], e["metric"], f"({e['period']})" if e["period"] else "") if x)
            out.append(f"  ├─ evidence {e['type']}: {head}{val}  [{e['confidence']}]")
            if e["source"]:
                out.append(f"  │    └─ source: {e['source']['label']}")
            elif e["text"]:
                out.append(f"  │    “{e['text'][:120]}”")
        for k in d["calculations"]:
            out.append(f"  ├─ calculation {k['name']} = {_fmt(k['result'])}{k['unit'] or ''}  "
                       f"[{k['expression']}]")
            for i in k["inputs"]:
                out.append(f"  │    • {i['name']} = {_fmt(i['value'])}")
        b = d["confidence_breakdown"]
        out.append(f"  └─ confidence = mean_support {b['mean_support']} × status_factor "
                   f"{b['status_factor']} = {b['claim_confidence']}")
        return "\n".join(out)

    # ------------------------------------------------------------------ #
    # whole-graph export
    # ------------------------------------------------------------------ #
    def to_graph(self, *, reachable_only: bool = False) -> dict:
        """`reachable_only=True` drops evidence/calculation/source nodes the reasoning
        pass gathered but no claim ever cites (§22/Phase-22: the public API endpoint uses
        this so a causal answer's ~48-evidence workspace doesn't dump in full)."""
        nodes: list[dict] = []
        edges: list[dict] = []
        seen: set[str] = set()

        def node(nid, ntype, label, **extra):
            if nid not in seen:
                seen.add(nid)
                nodes.append({"id": nid, "type": ntype, "label": label, **extra})

        for cid, cite in self._sources.items():
            node(cid, "source", cite.label(), uri=cite.uri)
        for e in self._ws:
            head = " ".join(x for x in (e.company, e.metric or e.type.value,
                                        f"({e.period})" if e.period else "") if x)
            node(e.evidence_id, "evidence", head or e.type.value, etype=e.type.value,
                 confidence=round(e.confidence, 4))
            for sub in e.inputs:
                if self._ws.get(sub):
                    edges.append({"from": e.evidence_id, "to": sub, "rel": "derived_from"})
            if e.citation is not None:
                edges.append({"from": e.evidence_id, "to": e.citation.citation_id, "rel": "cites"})
        for c in self._calcs.values():
            node(c.calculation_id, "calculation",
                 f"{c.name} = {_fmt(c.result)}{c.unit or ''}", kind=c.kind)
            for i in c.inputs:
                ei = i.get("evidence_id")
                if ei and self._ws.get(ei):
                    edges.append({"from": c.calculation_id, "to": ei, "rel": "computed_from"})
        for cl in self._g.claims:
            node(cl.claim_id, "claim", _clip(cl.text, 90),
                 status=cl.status.value, confidence=round(cl.confidence, 4), kind=cl.kind)
            for ei in cl.evidence_ids:
                if self._ws.get(ei):
                    edges.append({"from": cl.claim_id, "to": ei, "rel": "supported_by"})
            for ci in cl.calculation_ids:
                if ci in self._calcs:
                    edges.append({"from": cl.claim_id, "to": ci, "rel": "computed_by"})
        graph = {"nodes": nodes, "edges": edges}
        if reachable_only:
            graph = _filter_reachable(graph, start_ids={cl.claim_id for cl in self._g.claims})
        return graph

    def to_mermaid(self, *, reachable_only: bool = False) -> str:
        g = self.to_graph(reachable_only=reachable_only)
        ids = {n["id"]: f"n{i}" for i, n in enumerate(g["nodes"])}
        shape = {"claim": ('["', '"]'), "evidence": ('("', '")'),
                 "calculation": ('{{"', '"}}'), "source": ('[("', '")]')}
        lines = ["graph TD"]
        for n in g["nodes"]:
            o, c = shape.get(n["type"], ('["', '"]'))
            lines.append(f'  {ids[n["id"]]}{o}{_mermaid_escape(n["label"])}{c}')
        for e in g["edges"]:
            if e["from"] in ids and e["to"] in ids:
                lines.append(f'  {ids[e["from"]]} -->|{e["rel"]}| {ids[e["to"]]}')
        return "\n".join(lines)

    def to_dict(self, *, reachable_only: bool = False) -> dict:
        graph = self.to_graph(reachable_only=reachable_only)
        kept = {n["id"] for n in graph["nodes"]}
        sources = [self._source_node(c) for cid, c in self._sources.items()
                  if not reachable_only or cid in kept]
        if reachable_only:
            by_type = {"evidence": 0, "calculation": 0}
            for n in graph["nodes"]:
                if n["type"] in by_type:
                    by_type[n["type"]] += 1
            counts = {"claims": len(self._g.claims), "evidence": by_type["evidence"],
                     "calculations": by_type["calculation"], "sources": len(sources)}
        else:
            counts = {"claims": len(self._g.claims), "evidence": len(self._ws),
                     "calculations": len(self._calcs), "sources": len(self._sources)}
        return {
            "overall_confidence": round(self._g.overall_confidence(), 4),
            "counts": counts,
            "claims": [self.explain(cl) for cl in self._g.claims],
            "sources": sources,
            "graph": graph,
        }


def _filter_reachable(graph: dict, start_ids: set[str]) -> dict:
    """Nodes/edges reachable by following edges forward from `start_ids` (claims)."""
    adj: dict[str, list[str]] = {}
    for e in graph["edges"]:
        adj.setdefault(e["from"], []).append(e["to"])
    keep: set[str] = set()
    stack = list(start_ids)
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        keep.add(nid)
        stack.extend(adj.get(nid, []))
    return {
        "nodes": [n for n in graph["nodes"] if n["id"] in keep],
        "edges": [e for e in graph["edges"] if e["from"] in keep and e["to"] in keep],
    }


def _mermaid_escape(s: str) -> str:
    return re.sub(r'["\n]', " ", s).replace("(", "[").replace(")", "]")
