"""ingest_pdf: one results PDF -> DocumentMeta + provenance Source + structure-aware
chunks in finqa_v2.db. Idempotent (source sha256 + chunk replace).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from finqa_v2.documents.chunk import chunk_document
from finqa_v2.documents.extract import extract_pages
from finqa_v2.documents.sections import detect_sections
from finqa_v2.models import DocumentMeta, Source
from finqa_v2.normalize.periods import fiscal_year

_TS_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d_.]+_")
_WS = re.compile(r"\s+")
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


_CTRL = re.compile(r"[\x00-\x1f\x7f]|�")
_DASHES = {ord(c): "-" for c in "‐‑‒–—―−"}


def title_from_filename(name: str) -> str:
    stem = re.sub(r"\.pdf$", "", name, flags=re.I)
    stem = _TS_PREFIX.sub("", stem)
    stem = _CTRL.sub(" ", stem.translate(_DASHES))
    return _WS.sub(" ", stem.replace("_", " ")).strip(" -")


def document_type_of(title: str) -> str:
    t = title.lower()
    if "annual report" in t:
        return "annual_report"
    if "transcript" in t or "earnings call" in t:
        return "transcript"
    if "investor" in t and "presentation" in t:
        return "investor_presentation"
    return "results_pdf"


def period_and_fy(title: str, *, filename: str | None = None) -> tuple[str | None, int | None]:
    """Best-effort period label + Indian FY from a results-PDF title, falling back to
    the leading YYYY-MM-DD filing timestamp in the filename when the title has no date."""
    t = title
    # dd.mm.yyyy / dd-mm-yyyy / dd/mm/yyyy
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return m.group(0), fiscal_year(date(y, mo, d))
        except ValueError:
            pass
    # "March 31, 2026" / "31 March 2026" / "March 31 2026"
    m = re.search(r"(" + "|".join(_MONTHS) + r")\w*\.?\s+(\d{1,2})\D{0,3}(\d{4})", t, re.I)
    if m:
        mo, d, y = _MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        return m.group(0), fiscal_year(date(y, mo, d))
    m = re.search(r"(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\w*\.?\s+(\d{4})", t, re.I)
    if m:
        d, mo, y = int(m.group(1)), _MONTHS[m.group(2).lower()], int(m.group(3))
        return m.group(0), fiscal_year(date(y, mo, d))
    # "Q1 FY27" / "FY26" / "FY 2026"
    m = re.search(r"\bFY\s?'?(\d{2}(\d{2})?)\b", t, re.I)
    if m:
        yy = m.group(1)
        fy = int(yy) if len(yy) == 4 else 2000 + int(yy)
        return m.group(0), fy
    # fall back to the filing timestamp (YYYY-MM-DDT...) baked into the filename
    if filename:
        fm = re.match(r"(\d{4})-(\d{2})-(\d{2})T", filename)
        if fm:
            y, mo, d = map(int, fm.groups())
            try:
                return fm.group(0)[:10], fiscal_year(date(y, mo, d))
            except ValueError:
                pass
    return None, None


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def ingest_pdf(pdf_path: str | Path, repos, *, company: str | None = None,
               detect_tables: bool = True) -> dict:
    path = Path(pdf_path)
    symbol = company or path.parent.name
    co = repos.companies.resolve(symbol)
    if co is None:
        return {"file": path.name, "skipped": f"unknown company {symbol!r}", "chunks": 0}

    title = title_from_filename(path.name)
    document_type = document_type_of(title)
    period_label, fy = period_and_fy(title, filename=path.name)

    sha = _sha256(path)
    source = repos.sources.add(Source(
        kind="results_pdf", company_id=co.company_id, document_title=title,
        uri=str(path), content_hash=sha, retrieved_at=datetime.now(timezone.utc),
        period_label=period_label,
    ))

    result = extract_pages(path, known_sha256=sha, detect_tables=detect_tables)
    if not result.ok:
        return {"file": path.name, "company": symbol, "skipped": result.error, "chunks": 0}

    # De-dup on the file's sha256 (via its Source) only. Two different filings can share
    # a title ("Outcome Of Board Meeting"), so a title match must NOT collapse them.
    existing = repos.documents.find(co.company_id, source_id=source.source_id)
    doc = repos.documents.upsert(DocumentMeta(
        company_id=co.company_id, document_type=document_type, title=title,
        financial_year=fy, period_label=period_label, page_count=result.page_count,
        source_id=source.source_id,
        document_id=existing.document_id if existing else None,
    ))

    spans = detect_sections(result.pages)
    seg_slugs = [s.slug for s in repos.segments.segments_for(co.company_id)]
    chunks = chunk_document(
        result.pages, spans,
        document_id=doc.document_id, company_id=co.company_id,
        financial_year=fy, document_type=document_type, segment_slugs=seg_slugs,
    )
    repos.documents.delete_chunks(doc.document_id)
    n = repos.documents.add_chunks(chunks)

    return {
        "file": path.name, "company": symbol, "document_id": doc.document_id,
        "document_type": document_type, "financial_year": fy,
        "pages": result.page_count, "sections": len({s.section for s in spans}),
        "chunks": n, "tables": sum(1 for c in chunks if c.topic == "table"),
    }
