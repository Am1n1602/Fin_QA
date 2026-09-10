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
        if len(rendered) >= 20:
            rows_out.append(rendered)
    return rows_out


def extract_pages(pdf_path: str | Path, *, known_sha256: str | None = None,
                  detect_tables: bool = True) -> ExtractResult:
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
        body = _dominant_size(doc)
        pages: list[PageText] = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            headings = _page_headings(page, body)
            tables = _page_tables(page) if detect_tables else []
            pages.append(PageText(page_number=i, text=text, headings=headings, tables=tables))
        return ExtractResult(str(path), sha, len(pages), pages)
    except Exception as e:  # pragma: no cover
        return ExtractResult(str(path), sha, doc.page_count, error=f"extract_failed: {type(e).__name__}: {e}")
    finally:
        doc.close()
