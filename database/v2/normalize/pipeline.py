"""Canonical record -> list[FinancialFact], and canonical file -> facts persisted.

Input: data_extraction's *_canonical.json (tag-mapped + period-merged + arithmetic-
validated by v1). This layer adds unit, FY/quarter, basis, provenance, and the
Phase 1 fact grain. Missing fields are simply not emitted (absence == missing).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from database.v2.models import Basis, FinancialFact, MappingConfidence, Source
from database.v2.normalize import metrics
from database.v2.normalize.periods import normalize_period
from database.v2.normalize.units import currency_for
from database.v2.normalize.validate import validate_record

_META_KEYS = frozenset(
    {"context_id", "period_start", "period_end", "instant",
     "_missing_fields", "_validation", "_needs_review"}
)

_FILENAME_RE = re.compile(r"^(?P<symbol>.+)_(?P<basis>consolidated|standalone)_(?P<period>.+)_canonical\.json$")


def normalize_canonical_record(
    record: dict,
    company_id: int,
    basis: Basis | str,
    *,
    source_id: int | None = None,
) -> list[FinancialFact]:
    basis = Basis(basis)
    period = normalize_period(record.get("period_start"), record.get("period_end"), record.get("instant"))
    vres = validate_record(record)
    review_reason = (
        f"source record failed arithmetic checks: {', '.join(vres.failed)}"
        if vres.needs_review else None
    )

    facts: list[FinancialFact] = []
    for key, value in record.items():
        if key in _META_KEYS:
            continue
        spec = metrics.get(key)
        if spec is None:
            continue                                   # identifiers / untracked tags
        if value is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue                                   # absence == missing; skip non-numeric
        pit = spec.is_point_in_time
        facts.append(
            FinancialFact(
                company_id=company_id,
                metric=key,
                value=float(value),
                unit=spec.unit,
                currency=currency_for(key),
                period_start=None if pit else period.period_start,
                period_end=period.period_end,
                financial_year=period.financial_year,
                quarter=None if pit else period.quarter,
                statement_type=spec.statement_type,
                basis=basis,
                is_annual=period.is_annual and not pit,
                is_point_in_time=pit,
                source_id=source_id,
                mapping_confidence=MappingConfidence.EXACT,
                mapping_reason=review_reason,
            )
        )
    return facts


def _parse_filename(name: str) -> tuple[str, str, str] | None:
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    return m["symbol"], m["basis"], m["period"]


def normalize_canonical_file(path: Path, repos, *, source: Source | None = None) -> dict:
    """Resolve the company, register a Source for the file, normalize every record,
    and upsert the facts. Returns a small summary dict. Skips (does not raise) when
    the company can't be resolved."""
    path = Path(path)
    parsed = _parse_filename(path.name)
    if parsed is None:
        return {"file": path.name, "skipped": "unrecognized filename", "facts": 0}
    symbol, basis, period_label = parsed

    company = repos.companies.resolve(symbol)
    if company is None:
        return {"file": path.name, "skipped": f"unknown company {symbol!r}", "facts": 0}

    if source is None:
        source = Source(
            kind="xbrl",
            company_id=company.company_id,
            document_title=path.name,
            uri=str(path),
            content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            retrieved_at=datetime.now(timezone.utc),
            period_label=period_label,
        )
    stored_source = repos.sources.add(source)

    records = _read_json(path)
    n_facts = 0
    for record in records:
        facts = normalize_canonical_record(
            record, company.company_id, basis, source_id=stored_source.source_id
        )
        n_facts += repos.facts.add_many(facts)

    return {
        "file": path.name, "company": symbol, "basis": basis,
        "records": len(records), "facts": n_facts, "source_id": stored_source.source_id,
    }


def _read_json(path: Path) -> list[dict]:
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [data]
    return list(data)
