from __future__ import annotations
import re
from dataclasses import dataclass, field

from src.extraction.pdf_extractor import ExtractionResult, PageResult

_SECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"Sub\s*:", re.IGNORECASE), "cover_letter_subject"),
    (re.compile(r"(Select\s+)?[Ee]xplanatory\s+notes", re.IGNORECASE), "explanatory_notes"),
    (re.compile(r"(Independent\s+Auditor'?s?\s+Report|Report\s+on\s+the\s+audit)", re.IGNORECASE), "auditors_report"),
    (re.compile(r"Basis\s+for\s+Opinion", re.IGNORECASE), "auditors_report"),
    (re.compile(r"Annexure\b", re.IGNORECASE), "annexure"),
    (re.compile(r"Board\s+Meeting\s+Outcome", re.IGNORECASE), "board_meeting_outcome"),
]

DEFAULT_MIN_PAGE_CHARS = 40


@dataclass
class Chunk:
    chunk_index: int  # 0-indexed within this document
    text: str
    page_start: int
    page_end: int
    section: str | None  # heuristic, may be None
    char_count: int = field(init=False)
    approx_token_count: int = field(init=False)  # rough len(text)/4, NOT a real tokenizer

    def __post_init__(self):
        self.char_count = len(self.text)
        self.approx_token_count = max(1, self.char_count // 4)


@dataclass
class ChunkingResult:
    file_path: str
    chunks: list[Chunk]
    skipped_pages: list[dict]  # [{"page_number": int, "char_count": int, "reason": str}, ...]
    section_transitions: list[dict] = field(default_factory=list)

_REFERENCE_EXCLUSION = re.compile(
    r"(enclosed|attached|furnished|annexed|mentioned|specified|listed|referred|included)\s+"
    r"(at|as|in|to)\s*$", re.IGNORECASE)
_REFERENCE_SENSITIVE_LABELS = {"annexure"}


def _first_accepted_match(pattern: re.Pattern, label: str, text: str):
    for m in pattern.finditer(text):
        if label in _REFERENCE_SENSITIVE_LABELS:
            preceding = text[max(0, m.start() - 30): m.start()]
            if _REFERENCE_EXCLUSION.search(preceding):
                continue
        return m
    return None


def _detect_section(page_text: str) -> tuple[str, str] | None:
    best_pos = None
    best_label = None
    best_match = None
    for pattern, label in _SECTION_PATTERNS:
        m = _first_accepted_match(pattern, label, page_text)
        if m and (best_pos is None or m.start() < best_pos):
            best_pos = m.start()
            best_label = label
            best_match = m
    if best_label is None:
        return None
    ctx_start = max(0, best_match.start() - 40)
    ctx_end = min(len(page_text), best_match.end() + 40)
    snippet = page_text[ctx_start:ctx_end].replace("\n", " ")
    return best_label, snippet


def _group_into_runs(pages: list[PageResult], min_page_chars: int):
    """
    Returns (runs, skipped_pages) where runs is list[list[PageResult]].
    """
    runs: list[list[PageResult]] = []
    current_run: list[PageResult] = []
    skipped_pages: list[dict] = []

    for page in pages:
        if page.error is not None:
            skipped_pages.append({
                "page_number": page.page_number, "char_count": page.char_count,
                "reason": f"page_extraction_error: {page.error}",
            })
            if current_run:
                runs.append(current_run)
                current_run = []
            continue
        if page.char_count < min_page_chars:
            skipped_pages.append({
                "page_number": page.page_number, "char_count": page.char_count,
                "reason": "below_min_page_chars (likely image-only page, e.g. a "
                          "financial-results table already captured via XBRL)",
            })
            if current_run:
                runs.append(current_run)
                current_run = []
            continue
        current_run.append(page)

    if current_run:
        runs.append(current_run)

    return runs, skipped_pages


def _build_run_text(run: list[PageResult], current_section: str | None):
    """
    Builds the concatenated text + offset maps for ONE contiguous run of
    pages, updating section state as it goes. Returns
    (run_text, offset_page_map, offset_section_map, transitions, new_current_section).
    """
    parts: list[str] = []
    offset_page_map: list[tuple[int, int]] = []
    offset_section_map: list[tuple[int, str | None]] = []
    transitions: list[dict] = []
    cursor = 0

    for page in run:
        offset_page_map.append((cursor, page.page_number))

        detected = _detect_section(page.text)
        if detected:
            label, snippet = detected
            if label != current_section:
                current_section = label
                offset_section_map.append((cursor, current_section))
                transitions.append({
                    "page_number": page.page_number, "section": label, "matched_snippet": snippet,
                })

        parts.append(page.text)
        cursor += len(page.text) + 1  # +1 for the join separator added below

    run_text = "\n".join(parts)
    return run_text, offset_page_map, offset_section_map, transitions, current_section


def _lookup(offset_map: list[tuple[int, object]], pos: int, default=None):
    """Given a sorted (offset, value) list, return the value in effect at `pos`."""
    result = default
    for start, value in offset_map:
        if start <= pos:
            result = value
        else:
            break
    return result


def chunk_extraction_result(
    extraction: ExtractionResult,
    chunk_size: int = 1000, # Change this to increase the token size per chunk 
    overlap: int = 150,
    min_page_chars: int = DEFAULT_MIN_PAGE_CHARS,
) -> ChunkingResult:
    """

    Args:
        extraction: result from pdf_extractor.extract_pdf_text(). Must be
            .ok -- caller should check this before calling (a failed
            extraction has no pages to chunk).
        chunk_size: target characters per chunk. ~1000 chars ≈ 250 tokens,
            need to revisit.
        overlap: characters of overlap between consecutive chunks, so a
            sentence split across a chunk boundary still appears whole in
            at least one chunk.
        min_page_chars: pages with fewer extracted characters than this are
            skipped entirely (see DEFAULT_MIN_PAGE_CHARS docstring above).

    Returns:
        ChunkingResult with the chunk list and a record of skipped pages.
    """
    if not extraction.ok:
        return ChunkingResult(file_path=extraction.file_path, chunks=[], skipped_pages=[
            {"page_number": None, "char_count": 0, "reason": f"extraction_failed: {extraction.error}"}
        ])

    runs, skipped_pages = _group_into_runs(extraction.pages, min_page_chars)

    if not runs:
        return ChunkingResult(file_path=extraction.file_path, chunks=[], skipped_pages=skipped_pages)

    chunks: list[Chunk] = []
    all_transitions: list[dict] = []
    current_section: str | None = None
    chunk_index = 0
    step = max(1, chunk_size - overlap)

    for run in runs:
        section_at_run_start = current_section  # default for positions before any in-run change

        run_text, offset_page_map, offset_section_map, transitions, current_section = _build_run_text(
            run, current_section
        )
        all_transitions.extend(transitions)

        if not run_text.strip():
            continue

        pos = 0
        text_len = len(run_text)
        while pos < text_len:
            end = min(pos + chunk_size, text_len)
            chunk_text = run_text[pos:end].strip()

            if chunk_text:
                page_start = _lookup(offset_page_map, pos, default=run[0].page_number)
                page_end = _lookup(offset_page_map, end - 1, default=page_start)
                section = _lookup(offset_section_map, pos, default=section_at_run_start)

                chunks.append(Chunk(
                    chunk_index=chunk_index,
                    text=chunk_text,
                    page_start=page_start,
                    page_end=page_end,
                    section=section,
                ))
                chunk_index += 1

            if end == text_len:
                break
            pos += step

    return ChunkingResult(file_path=extraction.file_path, chunks=chunks, skipped_pages=skipped_pages,
                           section_transitions=all_transitions) 