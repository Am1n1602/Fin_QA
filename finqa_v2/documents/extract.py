"""Page-aware PDF extraction with PyMuPDF (§14).

Per page: clean text, heading candidates (font-size jump or ALL-CAPS short lines),
and detected tables rendered as tab-separated rows. Page numbers are 1-based and
survive downstream so any chunk can be cited to a page.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PageText:
    page_number: int
    text: str
    headings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    char_count: int = 0

    def __post_init__(self):
        self.char_count = len(self.text)


@dataclass(slots=True)
class ExtractResult:
    path: str
    sha256: str | None
    page_count: int
    pages: list[PageText] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


_CAPS_LINE = re.compile(r"^[A-Z0-9][A-Z0-9 ,.'&()\-/]{4,80}$")
_MOSTLY_DIGITS = re.compile(r"^[\d\s.,()%/₹-]+$")

# PyMuPDF's find_tables() frequently sweeps a page's letterhead (CIN, registered/corporate
# office, website, email, phone) into the same bounding box as the real data table right
# below it -- confirmed by direct inspection of ingested chunks (retrieval_v21 Phase 20
# investigation): every real table chunk for results-PDF companies re-embedded ~400+ chars
# of this boilerplate before the actual figures, diluting BM25/dense-embedding signal for
# every such chunk. These markers essentially never appear in a genuine financial-results
# line item, so dropping any table ROW that contains one is a safe, targeted strip -- never
# touches the surrounding prose chunks (those are handled separately by
# section_weights.yaml's existing `cover_letter: 0.3` suppression).
_TABLE_BOILERPLATE = re.compile(
    r"\bCIN\s*:|\bRegistered Office\b|\bCorporate Office\b|\bWebsite\s*:|\bE-?mail\b|"
    r"\bTelephone\b|\bFax\s*:",
    re.IGNORECASE,
)


def _strip_table_boilerplate(rendered: str) -> str:
    lines = [ln for ln in rendered.split("\n") if not _TABLE_BOILERPLATE.search(ln)]
    return "\n".join(lines)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _dominant_size(doc) -> float:
    counts: dict[float, int] = {}
    for page in doc:
        for b in page.get_text("dict").get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b["lines"]:
                for span in line["spans"]:
                    sz = round(span["size"], 1)
                    counts[sz] = counts.get(sz, 0) + len(span.get("text", ""))
    return max(counts, key=counts.get) if counts else 11.0


def _page_headings(page, body_size: float) -> list[str]:
    out: list[str] = []
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") != 0:
            continue
        for line in b["lines"]:
            spans = line["spans"]
            if not spans:
                continue
            txt = "".join(s["text"] for s in spans).strip()
            if not txt or len(txt) > 90 or _MOSTLY_DIGITS.match(txt):
                continue
            max_sz = max(s["size"] for s in spans)
            bold = any("bold" in (s.get("font", "").lower()) for s in spans)
            if max_sz >= body_size * 1.15 or (bold and len(txt) <= 70) or _CAPS_LINE.match(txt):
                out.append(txt)
    return out


def _page_tables(page) -> list[str]:
    try:
        found = page.find_tables()
    except Exception:
        return []
    rows_out: list[str] = []
    for tbl in getattr(found, "tables", []):
        try:
            data = tbl.extract()
        except Exception:
            continue
        lines = ["\t".join((c or "").strip().replace("\n", " ") for c in row) for row in data]
        rendered = "\n".join(l for l in lines if l.strip("\t ").strip())
        rendered = _strip_table_boilerplate(rendered)
        if len(rendered) >= 20:
            rows_out.append(rendered)
    return rows_out


# Phase 21: pymupdf_layout's box classes (a trained layout model, not a font-size/regex
# heuristic) that count as a heading vs. get excluded from prose entirely. Boilerplate
# (page-header/page-footer) is now dropped by POSITION -- the layout model already put
# it in its own box, structurally separate from the real content -- rather than by
# text-pattern matching after the fact (the old `_strip_table_boilerplate` approach,
# still used by the `--legacy` extraction path below for exact backward compatibility).
_HEADING_CLASSES = {"title", "section-header"}
_EXCLUDED_CLASSES = {"page-header", "page-footer", "picture", "footnote"}

# pymupdf_layout's own markdown table-cell assembly sometimes drops the space between
# adjacent words within a cell ("Total revenue from operations" -> "Totalrevenuefrom
# operations") -- confirmed by direct comparison against raw PyMuPDF text on the same
# region, which has always extracted this correctly (word-level bounding boxes show a
# real gap between adjacent words). This silently breaks exact-phrase keyword search
# (both the retrieval_v21 benchmark's own gold generation and production BM25
# tokenization -- a squished run breaks into one giant token instead of separate
# words). Fix: use pymupdf_layout ONLY for classifying table boxes (which regions are
# tables, and where) and pull the actual TEXT from that region via PyMuPDF's own
# `get_text("text", clip=...)`, which has never had this bug.
#
# Raw clipped text lists a table's label and its per-column values on SEPARATE lines
# (not one tab-separated row per line item), so a naive re-join would still merge every
# line item into one undifferentiated blob -- the exact problem this whole fix targets.
# `_group_logical_rows()` re-assembles each label with the value-looking lines that
# follow it (a "value" is numeric/currency-punctuation, a date, or an audited/unaudited
# tag) into one logical row, tab-joined -- producing the SAME row-per-line shape
# `finqa_v2/documents/chunk.py`'s table splitter already expects, so no changes are
# needed there.
_VALUE_LINE = re.compile(r"^[\d,.\-()%\s]*$|^\(?(un)?audited\)?$", re.I)
_DATE_LINE = re.compile(r"^\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}$")


def _is_value_line(line: str) -> bool:
    s = line.strip()
    return not s or bool(_VALUE_LINE.match(s)) or bool(_DATE_LINE.match(s))


def _group_logical_rows(lines: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    for ln in lines:
        if not groups or not _is_value_line(ln):
            groups.append([ln])
        else:
            groups[-1].append(ln)
    return groups


def _table_text_from_region(page, bbox) -> str:
    import pymupdf  # noqa: PLC0415

    raw = page.get_text("text", clip=pymupdf.Rect(*bbox))
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return ""
    groups = _group_logical_rows(lines)
    return "\n".join("\t".join(g) for g in groups)


def _extract_pages_layout(doc) -> list[PageText]:
    import pymupdf4llm  # noqa: PLC0415 -- optional/heavier dependency, only imported when used

    per_page = pymupdf4llm.to_markdown(doc, page_chunks=True)
    pages: list[PageText] = []
    for i, page_data in enumerate(per_page, start=1):
        page = doc[i - 1]
        text = page_data.get("text", "") or ""
        boxes = page_data.get("page_boxes") or []
        headings: list[str] = []
        tables: list[str] = []
        prose_spans: list[str] = []
        for box in boxes:
            cls = box.get("class")
            pos = box.get("pos")
            if not pos:
                continue
            start, end = pos
            span = text[start:end].strip()
            if not span:
                continue
            if cls == "table":
                bbox = box.get("bbox")
                table_text = _table_text_from_region(page, bbox) if bbox else span
                if table_text:
                    tables.append(table_text)
            elif cls in _HEADING_CLASSES:
                headings.append(span)
                prose_spans.append(span)
            elif cls not in _EXCLUDED_CLASSES:
                prose_spans.append(span)
        # boxes with no `pos` (or an empty page_boxes list entirely) fall back to the
        # page's own full markdown text, so a page pymupdf_layout doesn't segment at all
        # still contributes its content instead of silently vanishing.
        page_text = "\n\n".join(prose_spans) if prose_spans else text
        pages.append(PageText(page_number=i, text=page_text, headings=headings, tables=tables))
    return pages


def _extract_pages_legacy(doc, *, detect_tables: bool) -> list[PageText]:
    body = _dominant_size(doc)
    pages: list[PageText] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        headings = _page_headings(page, body)
        tables = _page_tables(page) if detect_tables else []
        pages.append(PageText(page_number=i, text=text, headings=headings, tables=tables))
    return pages


def extract_pages(pdf_path: str | Path, *, known_sha256: str | None = None,
                  detect_tables: bool = True, use_layout: bool = False) -> ExtractResult:
    """`use_layout=False` (default, Phase 21 REJECT): the original PyMuPDF-only path
    (`detect_tables` only applies here), with `_strip_table_boilerplate()`'s Phase 20
    text-pattern boilerplate removal.

    `use_layout=True`: pymupdf_layout's trained model segments each page into classed
    regions (table/section-header/page-header/page-footer/text/...) and
    `_group_logical_rows()` reassembles each table's real per-line-item rows (fixing a
    genuine pymupdf_layout bug -- its own markdown cell assembly drops spaces between
    words, e.g. "Totalrevenuefromoperations"). Verified correct in isolation against
    the exact case that motivated it (see docs/file-guide.md's Phase 21 write-up), but
    measured WORSE end-to-end on a real company's full document set: BAJAJFINSV
    recall@5 0.1765->0.0588 after a full re-ingest -- the row-grouping heuristic,
    calibrated against one quarterly-results table layout, produces malformed/
    incomplete groups on OTHER layouts in the same corpus (annual-report notes tables,
    segment breakdowns), adding noisy chunks rather than sharpening the right one.
    REJECTED as the default for production ingestion; kept as opt-in tooling for
    whoever picks up making the grouping heuristic format-agnostic (or adds a
    fallback to whole-table chunking when it can't confidently group a table)."""
    path = Path(pdf_path)
    if not path.exists():
        return ExtractResult(str(path), known_sha256, 0, error=f"file_not_found: {path}")
    try:
        import pymupdf  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        return ExtractResult(str(path), known_sha256, 0, error=f"pymupdf_not_installed: {e}")

    sha = known_sha256 or _sha256(path)
    try:
        doc = pymupdf.open(str(path))
    except Exception as e:
        return ExtractResult(str(path), sha, 0, error=f"open_failed: {type(e).__name__}: {e}")

    try:
        if use_layout:
            try:
                pages = _extract_pages_layout(doc)
            except ImportError:
                pages = _extract_pages_legacy(doc, detect_tables=detect_tables)
        else:
            pages = _extract_pages_legacy(doc, detect_tables=detect_tables)
        return ExtractResult(str(path), sha, len(pages), pages)
    except Exception as e:  # pragma: no cover
        return ExtractResult(str(path), sha, doc.page_count, error=f"extract_failed: {type(e).__name__}: {e}")
    finally:
        doc.close()
