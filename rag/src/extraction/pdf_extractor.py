"""
pdf_extractor.py — Stage 9 (RAG), Phase 1: PDF text extraction.

STATUS: Built but NOT YET validated against real downloaded PDFs (the 118
BSE/NSE filings inventoried via pdf_downloader.py's data/meta/{symbol}_filings.jsonl
live on the user's machine, not in this environment). Smoke-tested here only
against a synthetic single-page PDF to confirm the code runs without crashing.
Must be re-validated against real BSE-sourced filings before Phase 2 (chunking)
begins, per this project's "validate on real output before scaling" convention.

Uses pypdf (per Stage 9 plan — no OCR pipeline; all 118 inventoried PDFs were
already confirmed genuinely text-based during the earlier inventory pass).

Design notes:
- Extraction is per-page, preserving page_number, because document_chunks.page_number
  is part of the planned Stage 9 DB schema (SESSION_ADDENDUM.md) and chunks need to
  trace back to a specific page.
- Never silently drops a bad page or a bad file. A per-page failure is recorded in
  that page's `error` field with an empty text string; a whole-file failure (corrupt
  PDF, encrypted PDF, unreadable) is surfaced as a top-level `error` field with
  `pages: []` rather than raising — this project's "missing data surfaces as null +
  reason, never silently hidden" rule, applied to extraction rather than financial
  data.
- `low_text_page_numbers` flags pages whose extracted-char-count-per-page falls well
  below the document's own average. This is a MISMATCH DETECTOR, not an OCR-need
  detector — the inventory already confirmed these PDFs are text-based, so a low-text
  page more likely means a mostly-image/table/signature page than a scan. Surfaced so
  a human can glance at flagged pages, not auto-handled.
- No chunking here. This module's only job is: PDF path -> per-page text + diagnostics.
  Chunking is Phase 2, deliberately kept separate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError


@dataclass
class PageResult:
    page_number: int  # 1-indexed, matches how humans/citations reference PDF pages
    text: str
    char_count: int
    error: Optional[str] = None


@dataclass
class ExtractionResult:
    file_path: str
    sha256: Optional[str]
    page_count: int
    pages: list[PageResult] = field(default_factory=list)
    total_chars: int = 0
    low_text_page_numbers: list[int] = field(default_factory=list)
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
) -> ExtractionResult:
    """
    Extract per-page text from a single PDF.

    Args:
        pdf_path: path to the PDF file.
        known_sha256: pass the hash already computed by pdf_downloader.py if
            available, to avoid recomputing it. If None, computes it here.
        low_text_ratio_threshold: a page is flagged in `low_text_page_numbers`
            if its char_count < threshold * (document's average char_count
            across non-empty pages). Purely diagnostic, not a decision.

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

    # Magic-byte check BEFORE handing off to pypdf. A file that doesn't even
    # start with %PDF- almost always means the downloader saved something
    # else entirely (an HTML error/rate-limit/redirect page, a login wall,
    # etc.) rather than a genuinely corrupted PDF. These need different fixes
    # (re-download vs. something wrong with the PDF itself), so distinguish
    # them instead of letting both surface as the same generic pypdf error.
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
        # Try an empty-password unlock (some filings are "encrypted" only to
        # prevent editing, not to require a real password). If that fails,
        # surface it rather than silently returning zero pages.
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
    )