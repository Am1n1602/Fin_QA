from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.extraction.ocr_backend import ocr_page


@dataclass
class PageResult:
    page_number: int  # 1-indexed, matches how humans/citations reference PDF pages
    text: str
    char_count: int
    error: Optional[str] = None
    ocr_used: bool = False  # True if this page's text came from OCR, not the PDF's own text layer


@dataclass
class ExtractionResult:
    file_path: str
    sha256: Optional[str]
    page_count: int
    pages: list[PageResult] = field(default_factory=list)
    total_chars: int = 0
    low_text_page_numbers: list[int] = field(default_factory=list)
    ocr_used_page_numbers: list[int] = field(default_factory=list)
    ocr_unavailable: bool = False  # True if a page needed OCR but it couldn't run
    ocr_unavailable_reason: Optional[str] = None
    error: Optional[str] = None  # whole-file failure only

    @property
    def ok(self) -> bool:
        return self.error is None

    def full_text(self, page_separator: str = "\n\n") -> str:
        """Concatenate all page text in order. Convenience for a first look;
        Phase 2 (chunking) should use `pages` directly to preserve page_number,
        not this flattened string."""
        return page_separator.join(p.text for p in self.pages)


def _sha256_of_file(path: Path) -> str:
    """Independent hash computation for this module's own use (e.g. dedup /
    change-detection on files handed to it directly). NOT a replacement for
    pdf_downloader.py's existing hash — when a file's hash is already known
    from data/meta/{symbol}_filings.jsonl, pass and trust that one instead of
    recomputing; this is only a fallback for standalone use."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pdf_text(
    pdf_path: str | Path,
    known_sha256: Optional[str] = None,
    low_text_ratio_threshold: float = 0.15,
    enable_ocr: bool = True,
    ocr_char_threshold: int = 50,
    ocr_dpi: int = 300,
) -> ExtractionResult:
    """
    Extract per-page text from a single PDF, falling back to OCR for pages
    whose own text layer is missing or near-empty.

    Args:
        pdf_path: path to the PDF file.
        known_sha256: pass the hash already computed by pdf_downloader.py if
            available, to avoid recomputing it. If None, computes it here.
        low_text_ratio_threshold: a page is flagged in `low_text_page_numbers`
            if its char_count < threshold * (document's average char_count
            across non-empty pages). Purely diagnostic, not a decision.
        enable_ocr: if True (default), pages at or below `ocr_char_threshold`
            characters get a second pass through OCR (ocr_backend.ocr_page).
            OCR's result replaces the page's text only when it actually
            yields more text than pypdf found -- OCR is never allowed to
            make a page worse. Set False to keep the old pypdf-only
            behavior (e.g. for a fast mechanics-only test run).
        ocr_char_threshold: a page with fewer than this many pypdf-extracted
            characters is treated as a candidate scan and sent to OCR. This
            is an ABSOLUTE floor, unlike low_text_ratio_threshold, because a
            fully-scanned document has no non-empty pages to average
            against (every page would be 0 vs. an average of 0).
        ocr_dpi: render resolution passed to ocr_backend.ocr_page. 300 is a
            reasonable default for Tesseract accuracy vs. speed on typical
            filing-scan quality; raise it if OCR output looks garbled on a
            specific document.

    Returns:
        ExtractionResult. Check `.ok` before using `.pages` — a whole-file
        failure returns `.error` set and `.pages == []`, never raises.
    """
    path = Path(pdf_path)

    if not path.exists():
        return ExtractionResult(
            file_path=str(path),
            sha256=known_sha256,
            page_count=0,
            error=f"file_not_found: {path}",
        )

    sha256 = known_sha256 or _sha256_of_file(path)

    with open(path, "rb") as f:
        head = f.read(16)
    if not head.startswith(b"%PDF-"):
        preview = head[:12]
        return ExtractionResult(
            file_path=str(path), sha256=sha256, page_count=0,
            error=f"not_a_pdf_file: does not start with %PDF- (first bytes: {preview!r}) "
                  f"— likely the downloader saved a non-PDF response (HTML error/redirect/"
                  f"rate-limit page) instead of the real file. Re-download, don't re-parse.",
        )

    try:
        reader = PdfReader(str(path))
    except PdfReadError as e:
        return ExtractionResult(
            file_path=str(path), sha256=sha256, page_count=0,
            error=f"pdf_read_error: {e}",
        )
    except Exception as e:  # genuinely unknown failure mode — surface, don't hide
        return ExtractionResult(
            file_path=str(path), sha256=sha256, page_count=0,
            error=f"unexpected_error: {type(e).__name__}: {e}",
        )

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            pass
        if reader.is_encrypted:
            return ExtractionResult(
                file_path=str(path), sha256=sha256, page_count=0,
                error="encrypted_pdf_could_not_decrypt",
            )

    pages: list[PageResult] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            pages.append(PageResult(page_number=i, text="", char_count=0, error=str(e)))
            continue
        pages.append(PageResult(page_number=i, text=text, char_count=len(text)))

    ocr_used_page_numbers: list[int] = []
    ocr_unavailable = False
    ocr_unavailable_reason: Optional[str] = None
    if enable_ocr:
        for p in pages:
            if p.error is not None or p.char_count > ocr_char_threshold:
                continue
            result = ocr_page(path, p.page_number, dpi=ocr_dpi)
            if not result.ok:
                ocr_unavailable = True
                ocr_unavailable_reason = result.error
                continue
            ocr_text = result.text or ""
            if len(ocr_text) > p.char_count:
                p.text = ocr_text
                p.char_count = len(ocr_text)
                p.ocr_used = True
                ocr_used_page_numbers.append(p.page_number)

    total_chars = sum(p.char_count for p in pages)

    non_empty = [p.char_count for p in pages if p.error is None and p.char_count > 0]
    low_text_pages: list[int] = []
    if non_empty:
        avg = sum(non_empty) / len(non_empty)
        threshold = avg * low_text_ratio_threshold
        for p in pages:
            if p.error is None and p.char_count < threshold:
                low_text_pages.append(p.page_number)

    return ExtractionResult(
        file_path=str(path),
        sha256=sha256,
        page_count=len(pages),
        pages=pages,
        total_chars=total_chars,
        low_text_page_numbers=low_text_pages,
        ocr_used_page_numbers=ocr_used_page_numbers,
        ocr_unavailable=ocr_unavailable,
        ocr_unavailable_reason=ocr_unavailable_reason,
    )
