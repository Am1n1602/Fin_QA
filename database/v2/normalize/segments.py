"""Extract reportable-segment revenue from *_facts_raw.json (§12).

Only the whole-segment contexts are used: `<Prefix>Reportable<N>D` (N = 1..29,
Prefix = One/Two/.../Six), and only when the context carries BOTH a
`DescriptionOfReportableSegment` (name) and a `SegmentRevenue` value. That test
excludes the note/asset sub-breakdown contexts (`OneReportable31D`, `...Finance...`).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from database.v2.models import Basis, Segment, SegmentFact, Source
from database.v2.normalize.periods import normalize_period
from database.v2.normalize.pipeline import _parse_filename

_SEG_CTX = re.compile(r"^(?:One|Two|Three|Four|Five|Six)Reportable(?:[1-9]|1\d|2\d)D$")

# raw XBRL tag (local name) -> our segment metric name
_METRIC_TAGS = {
    "SegmentRevenue": "segment_revenue",
    "SegmentRevenueFromOperations": "segment_revenue",
    "SegmentProfitLossBeforeTaxAndFinanceCosts": "segment_result",
    "SegmentProfitBeforeTax": "segment_result",
    "SegmentAssets": "segment_assets",
    "SegmentLiabilities": "segment_liabilities",
    "InterSegmentRevenue": "inter_segment_revenue",
}
_NAME_TAG = "DescriptionOfReportableSegment"


def _local(tag: str | None) -> str:
    return (tag or "").split(":")[-1]


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def extract_segments(
    raw_facts: list[dict],
    company_id: int,
    basis: Basis | str,
    *,
    source_id: int | None = None,
) -> tuple[list[Segment], list[tuple[str, SegmentFact]]]:
    """Returns (segments, [(segment_name, fact_with_placeholder_segment_id), ...]).
    The caller persists the segments, then rebinds segment_id by name."""
    basis = Basis(basis)
    by_ctx: dict[str, dict] = {}
    for f in raw_facts:
        ctx = f.get("context_id") or ""
        if not _SEG_CTX.match(ctx):
            continue
        d = by_ctx.setdefault(ctx, {"name": None, "metrics": {}, "period": None})
        local = _local(f.get("line_item_tag"))
        if local == _NAME_TAG:
            d["name"] = (f.get("value") or "").strip() or d["name"]
        elif local in _METRIC_TAGS:
            d["metrics"].setdefault(_METRIC_TAGS[local], _num(f.get("value")))
        if d["period"] is None:
            d["period"] = (f.get("period_start"), f.get("period_end"), f.get("instant"))

    segments: dict[str, Segment] = {}
    named: list[tuple[str, SegmentFact]] = []
    for d in by_ctx.values():
        name = d["name"]
        if not name or d["metrics"].get("segment_revenue") is None:
            continue                                     # not a real whole-segment context
        segments.setdefault(name, Segment(company_id=company_id, name=name))
        ps, pe, inst = d["period"]
        p = normalize_period(ps, pe, inst)
        for metric, value in d["metrics"].items():
            if value is None:
                continue
            named.append((name, SegmentFact(
                segment_id=-1, company_id=company_id, metric=metric, value=value, basis=basis,
                unit="INR", period_start=p.period_start, period_end=p.period_end,
                financial_year=p.financial_year, quarter=p.quarter, is_annual=p.is_annual,
                source_id=source_id,
            )))
    return list(segments.values()), named


def extract_and_store(raw_path: Path, repos, *, source: Source | None = None) -> dict:
    raw_path = Path(raw_path)
    name = raw_path.name.replace("_facts_raw.json", "_canonical.json")
    parsed = _parse_filename(name)
    if parsed is None:
        return {"file": raw_path.name, "skipped": "unrecognized filename", "segments": 0, "facts": 0}
    symbol, basis, period_label = parsed

    company = repos.companies.resolve(symbol)
    if company is None:
        return {"file": raw_path.name, "skipped": f"unknown company {symbol!r}", "segments": 0, "facts": 0}

    raw_facts = json.loads(raw_path.read_text(encoding="utf-8"))
    segs, named_facts = extract_segments(raw_facts, company.company_id, basis)  # type: ignore[misc]
    if not segs:
        return {"file": raw_path.name, "company": symbol, "segments": 0, "facts": 0}

    if source is None:
        source = Source(
            kind="xbrl_segment",
            company_id=company.company_id,
            document_title=raw_path.name,
            uri=str(raw_path),
            content_hash=hashlib.sha256(raw_path.read_bytes()).hexdigest(),
            retrieved_at=datetime.now(timezone.utc),
            period_label=period_label,
        )
    stored_source = repos.sources.add(source)

    slug_to_id: dict[str, int] = {}
    for seg in segs:
        stored = repos.segments.upsert_segment(seg)
        slug_to_id[seg.slug] = stored.segment_id

    from database.v2.models import slugify

    facts = []
    for seg_name, f in named_facts:
        sid = slug_to_id[slugify(seg_name)]
        facts.append(SegmentFact(
            segment_id=sid, company_id=f.company_id, metric=f.metric, value=f.value, basis=f.basis,
            unit=f.unit, period_start=f.period_start, period_end=f.period_end,
            financial_year=f.financial_year, quarter=f.quarter, is_annual=f.is_annual,
            source_id=stored_source.source_id,
        ))
    n = repos.segments.add_facts(facts)
    return {"file": raw_path.name, "company": symbol, "basis": basis,
            "segments": len(segs), "facts": n, "source_id": stored_source.source_id}
