"""Build a tiny 3-page results-style PDF with PyMuPDF for section-detection tests."""
from __future__ import annotations

from pathlib import Path

_PAGES = [
    # page 1 -- cover letter
    ("Cover", 11,
     "BSE Limited\nDear Sir/Madam,\n\n"
     "Sub: Audited Financial Results for the quarter and year ended 31.03.2026\n\n"
     "With reference to the above, we enclose herewith the audited financial results "
     "of the Company for the quarter and year ended March 31, 2026, as approved by the "
     "Board of Directors at its meeting held today.\n\n"
     "The results were driven by higher volumes in the domestic market and improved "
     "realisations. Kindly take the same on record."),
    # page 2 -- auditor's report
    ("INDEPENDENT AUDITOR'S REPORT", 16,
     "INDEPENDENT AUDITOR'S REPORT\n\n"
     "To the Board of Directors\n\n"
     "We have audited the accompanying statement of financial results of the Company.\n\n"
     "Basis for Opinion\n\n"
     "We conducted our audit in accordance with the Standards on Auditing. Our "
     "responsibilities are described further in our report. We believe the evidence "
     "obtained is sufficient and appropriate to provide a basis for our opinion."),
    # page 3 -- segment information
    ("Segment Information", 16,
     "Segment Information\n\n"
     "The Group has identified the following reportable segments: Retail, Digital "
     "Services and Oil to Chemicals. Segment revenue for the year is presented below.\n\n"
     "Inter-segment transfers are eliminated on consolidation. The Retail segment "
     "reported the highest growth during the year."),
]


def make_results_pdf(path: str | Path) -> Path:
    import pymupdf

    path = Path(path)
    doc = pymupdf.open()
    for heading, size, body in _PAGES:
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), heading, fontsize=size, fontname="helv")
        y = 110
        for line in body.split("\n"):
            page.insert_text((72, y), line, fontsize=11, fontname="helv")
            y += 16
    doc.save(str(path))
    doc.close()
    return path
