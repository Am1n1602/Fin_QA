"""Structure-aware chunking (§15): per section, pack paragraph groups to a target size
with small overlap, breaking only at paragraph boundaries. A small table stays its own
single chunk; a LARGE one (Phase 21) splits into row-groups, each repeating the
table's own leading lines for context, so a specific line-item query finds a small,
concentrated chunk instead of one big chunk averaging 20-30 unrelated line items --
the confirmed dominant cause of a retrieval-precision regression traced this session
(see docs/file-guide.md's Phase 20 fourth/Phase 21 write-ups). Only viable with the
pymupdf_layout-based extraction (finqa_v2/documents/extract.py): the older raw
PyMuPDF find_tables() merged every line item into one blob with no `\n` between them
at all, so there was nothing to split on. Every chunk keeps page + section provenance
and the §15 metadata.
"""
from __future__ import annotations

import re

from finqa_v2.models import DocumentChunk

_PARA_SPLIT = re.compile(r"\n\s*\n+")
_WS = re.compile(r"[ \t]+")

_TARGET = 900
_OVERLAP = 120
_MIN = 200

# A table at or under this size stays exactly one chunk, unchanged from before Phase 21
# -- the vast majority of detected tables (subsidiary lists, small summary tables) are
# well under this and see byte-identical behavior. Smaller than prose's 900-char target
# since tables are already denser per character.
_TABLE_SPLIT_TARGET = 500
# Leading lines repeated verbatim in EVERY split group so each stays interpretable
# without its column headers -- calibrated against a real financial-results table
# extracted via extract.py's `_group_logical_rows()` (which folds a table's own
# period-dates/audited-status lines into whichever label preceded them): "Particulars"
# / "Quarter ended" / "Year ended"+dates+audited-tags = 3 logical rows before the
# first real line item; see docs/file-guide.md. For tables with fewer real header rows
# (e.g. a 1-row subsidiary-list header), this harmlessly folds 1-2 data rows into the
# repeated prefix too -- redundant, never lossy.
_TABLE_HEADER_LINES = 3


def _split_table(rendered: str, *, target: int = _TABLE_SPLIT_TARGET,
                 header_lines: int = _TABLE_HEADER_LINES) -> list[str]:
    """A table at/under `target` chars is returned whole (list of 1). Longer ones split
    on `\n` (real row boundaries -- only present when extraction actually preserved
    them) into groups near `target` chars, each prefixed with the table's own first
    `header_lines` lines so it's still readable as "this line item, under this column
    header" without needing the rest of the table."""
    if len(rendered) <= target:
        return [rendered]
    lines = rendered.split("\n")
    if len(lines) <= header_lines + 1:
        return [rendered]
    header_text = "\n".join(lines[:header_lines])
    body = lines[header_lines:]
    groups: list[str] = []
    buf: list[str] = []
    size = len(header_text)
    for ln in body:
        if buf and size + len(ln) > target:
            groups.append(header_text + "\n" + "\n".join(buf))
            buf = []
            size = len(header_text)
        buf.append(ln)
        size += len(ln) + 1
    if buf:
        groups.append(header_text + "\n" + "\n".join(buf))
    return groups


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
        # tables first -- one chunk each. Phase 21 built _split_table() to break a large
        # table into smaller row-groups, but measured a real end-to-end regression when
        # applied broadly: some real tables (e.g. an annual-report notes section with a
        # "Note No." column) already come out of PyMuPDF's find_tables() with labels and
        # values misaligned on complex layouts, and splitting that already-imperfect
        # content made it worse rather than better, independent of the separate
        # word-spacing bug _split_table() itself has nothing to do with. REJECTED as
        # the default -- _split_table() stays defined and tested for whoever redesigns
        # this with a confidence check (only split a table verified well-formed).
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
