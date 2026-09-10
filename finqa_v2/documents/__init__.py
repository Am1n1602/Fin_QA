"""PDF -> page-aware text -> sections -> structure-aware chunks. See docs/file-guide.md."""
from __future__ import annotations

from .chunk import chunk_document
from .extract import PageText, extract_pages
from .pipeline import ingest_pdf
from .sections import SectionSpan, detect_sections

__all__ = [
    "PageText",
    "SectionSpan",
    "chunk_document",
    "detect_sections",
    "extract_pages",
    "ingest_pdf",
]
