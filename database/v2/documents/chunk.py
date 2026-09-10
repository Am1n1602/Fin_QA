"""Structure-aware chunking (§15): per section, pack paragraph groups to a target size
with small overlap, breaking only at paragraph boundaries. Tables become their own
chunk (never split, never merged). Every chunk keeps page + section provenance and the
§15 metadata.
"""
from __future__ import annotations

import re

from database.v2.models import DocumentChunk

_PARA_SPLIT = re.compile(r"\n\s*\n+")
_WS = re.compile(r"[ \t]+")

_TARGET = 900
_OVERLAP = 120
_MIN = 200


def _clean(text: str) -> str:
    lines = [_WS.sub(" ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _paragraphs(pages) -> list[tuple[str, int]]:
    """[(paragraph_text, page_number), ...] in reading order."""
    out: list[tuple[str, int]] = []
    for p in pages:
        for para in _PARA_SPLIT.split(_clean(p.text)):
            para = para.strip()
            if para:
                out.append((para, p.page_number))
    return out


def _pack(paras: list[tuple[str, int]], target: int, overlap: int, min_chunk: int):
    """Yield (text, page_start, page_end). Overlap = repeat the trailing tail of the
    previous chunk (<= `overlap` chars, whole paragraphs only) at the front of the next."""
    chunks: list[tuple[str, int, int]] = []
    buf: list[tuple[str, int]] = []
    size = 0
    for para, page in paras:
        if size and size + len(para) > target:
            text = "\n\n".join(t for t, _ in buf)
            chunks.append((text, buf[0][1], buf[-1][1]))
            # build overlap tail
            tail: list[tuple[str, int]] = []
            tlen = 0
            for t, pg in reversed(buf):
                if tlen + len(t) > overlap and tail:
                    break
                tail.insert(0, (t, pg))
                tlen += len(t)
            buf = tail
            size = sum(len(t) for t, _ in buf)
        buf.append((para, page))
        size += len(para)
    if buf:
        text = "\n\n".join(t for t, _ in buf)
        if chunks and len(text) < min_chunk:
            prev_t, ps, _ = chunks[-1]
            chunks[-1] = (prev_t + "\n\n" + text, ps, buf[-1][1])
        else:
            chunks.append((text, buf[0][1], buf[-1][1]))
    return chunks


def _segment_of(text: str, segment_slugs) -> str | None:
    low = text.lower()
    for slug in segment_slugs:
        if slug and slug.replace("_", " ") in low:
            return slug
    return None


def chunk_document(
    pages,
    sections,
    *,
    document_id: int,
    company_id: int,
    financial_year: int | None,
    document_type: str | None,
    segment_slugs=(),
    target: int = _TARGET,
    overlap: int = _OVERLAP,
    min_chunk: int = _MIN,
) -> list[DocumentChunk]:
    by_page = {p.page_number: p for p in pages}
    segment_slugs = tuple(segment_slugs)
    chunks: list[DocumentChunk] = []
    idx = 0

    def _add(text, page_start, page_end, section, topic, segment):
        nonlocal idx
        chunks.append(DocumentChunk(
            document_id=document_id, company_id=company_id, chunk_index=idx, text=text,
            page_start=page_start, page_end=page_end, section=section, subsection=None,
            financial_year=financial_year, document_type=document_type,
            topic=topic, segment=segment,
        ))
        idx += 1

    for span in sections:
        span_pages = [by_page[n] for n in range(span.page_start, span.page_end + 1) if n in by_page]
        if not span_pages:
            continue
        # tables first -- one chunk each
        for p in span_pages:
            for tbl in p.tables:
                _add(tbl, p.page_number, p.page_number, span.section, "table",
                     _segment_of(tbl, segment_slugs))
        # then prose
        default_topic = "segment" if span.section == "segment_information" else "prose"
        for text, ps, pe in _pack(_paragraphs(span_pages), target, overlap, min_chunk):
            _add(text, ps, pe, span.section, default_topic, _segment_of(text, segment_slugs))

    return chunks


def default_params() -> dict:
    return {"target": _TARGET, "overlap": _OVERLAP, "min_chunk": _MIN}
