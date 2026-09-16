"""Section detection over extracted pages (§14). Produces contiguous page spans, each
labelled with a section (and optional subsection). Unmatched leading pages -> 'cover_letter'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ordered: earlier rules win when several match on the same page
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"independent\s+auditor'?s?\s+report", re.I), "auditors_report"),
    (re.compile(r"review\s+report\s+to\s+the\s+board", re.I), "auditors_report"),
    (re.compile(r"basis\s+for\s+(qualified\s+|adverse\s+|disclaimer\s+of\s+)?opinion", re.I), "auditors_report"),
    (re.compile(r"statement\s+of\s+(standalone|consolidated|unaudited|audited).{0,40}?financial\s+results", re.I), "financial_results"),
    (re.compile(r"(statement\s+of\s+)?(consolidated\s+|standalone\s+)?cash\s*flows?\s+statement", re.I), "cash_flow_statement"),
    (re.compile(r"(statement\s+of\s+)?(consolidated\s+|standalone\s+)?balance\s+sheet", re.I), "balance_sheet"),
    (re.compile(r"segment(al)?\s+(information|revenue|results|reporting)", re.I), "segment_information"),
    (re.compile(r"notes?\s+to\s+the\s+(financial\s+results|statement|accounts)", re.I), "notes"),
    (re.compile(r"^\s*notes?\s*:?\s*$", re.I | re.M), "notes"),
    (re.compile(r"management\s+discussion\s+and\s+analysis", re.I), "mda"),
    (re.compile(r"risk\s+(factors|management)", re.I), "risk_factors"),
    (re.compile(r"outcome\s+of\s+(the\s+)?board\s+meeting", re.I), "board_meeting_outcome"),
    # --- annual-report sections (Phase 15: for when annual reports / transcripts land) ---
    (re.compile(r"(board'?s?|directors?'?)\s+report\b", re.I), "board_report"),
    (re.compile(r"report\s+on\s+corporate\s+governance|corporate\s+governance\s+report", re.I),
     "corporate_governance"),
    (re.compile(r"business\s+responsibility\s+(and\s+sustainability\s+)?report|\bBRSR\b", re.I),
     "brsr"),
    (re.compile(r"notice\s+of\s+(the\s+)?(\w+\s+)?annual\s+general\s+meeting|\bnotice\s+is\s+hereby\s+given\b", re.I),
     "notice"),
    (re.compile(r"secretarial\s+audit\s+report", re.I), "secretarial_audit"),
    (re.compile(r"(managing\s+director|chairman)'?s?\s+(message|statement|letter|review)", re.I),
     "leadership_message"),
    (re.compile(r"(analyst|earnings|investor|conference)\s+call\s+transcript|"
                r"transcript\s+of\s+(the\s+)?(earnings|analyst|investor)\s+call", re.I),
     "earnings_call"),
    (re.compile(r"annexure\b", re.I), "annexure"),
    (re.compile(r"\bsub\s*:", re.I), "cover_letter"),
]

# reference phrases like "enclosed as Annexure A" should NOT flip the section
_REF_BEFORE = re.compile(
    r"(enclosed|attached|furnished|annexed|refer(red)?|as\s+per|vide|mentioned|see)\s+"
    r"(to\s+|in\s+|at\s+|as\s+)?$", re.I
)


@dataclass(frozen=True, slots=True)
class SectionSpan:
    section: str
    subsection: str | None
    page_start: int
    page_end: int


def _match_on(text: str) -> str | None:
    best_pos, best_label = None, None
    for pat, label in _RULES:
        for m in pat.finditer(text):
            pre = text[max(0, m.start() - 40): m.start()]
            if _REF_BEFORE.search(pre):
                continue
            if best_pos is None or m.start() < best_pos:
                best_pos, best_label = m.start(), label
            break
    return best_label


def detect_sections(pages) -> list[SectionSpan]:
    if not pages:
        return []
    # per-page label: prefer a heading match, else a body-text match
    page_label: list[str | None] = []
    for p in pages:
        lab = None
        for h in p.headings:
            lab = _match_on(h)
            if lab:
                break
        if lab is None:
            lab = _match_on(p.text[:2500])
        page_label.append(lab)

    # carry forward; leading None -> cover_letter
    resolved: list[str] = []
    current = "cover_letter"
    for lab in page_label:
        if lab is not None:
            current = lab
        resolved.append(current)

    spans: list[SectionSpan] = []
    start = pages[0].page_number
    for idx in range(1, len(pages) + 1):
        if idx == len(pages) or resolved[idx] != resolved[idx - 1]:
            spans.append(SectionSpan(resolved[idx - 1], None, start, pages[idx - 1].page_number))
            if idx < len(pages):
                start = pages[idx].page_number
    return spans
