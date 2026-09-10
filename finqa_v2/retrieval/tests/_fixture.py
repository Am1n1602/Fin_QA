"""In-memory repo with a handful of document_chunks for retrieval tests."""
from __future__ import annotations

from finqa_v2.models import Company, DocumentChunk, DocumentMeta

_CHUNKS = [
    # (company_ticker, section, topic, text)
    ("RELIANCE", "segment_information", "segment",
     "The Group operates in reportable segments Oil to Chemicals, Retail and Digital "
     "Services. Segment revenue for Retail grew strongly during the year."),
    ("RELIANCE", "auditors_report", "prose",
     "Independent Auditor's Report. We have audited the accompanying statement of "
     "financial results. Basis for Opinion: we conducted our audit in accordance with "
     "the Standards on Auditing."),
    ("RELIANCE", "cover_letter", "prose",
     "Sub: Outcome of Board Meeting under SEBI Listing Obligations and Disclosure "
     "Requirements Regulations 2015. The Board recommended a final dividend."),
    ("TCS", "segment_information", "segment",
     "TCS reportable segments include Banking Financial Services and Insurance, "
     "Manufacturing and Life Sciences. BFSI is the largest segment by revenue."),
    ("TCS", "financial_results", "table",
     "Revenue from operations 267021. Profit for the period 48553. Earnings per share "
     "basic. Total comprehensive income for the period."),
    ("TCS", "notes", "prose",
     "The results were reviewed by the Audit Committee and approved by the Board of "
     "Directors. Exceptional items include the statutory impact of new Labour Codes."),
    ("INFY", "cash_flow_statement", "table",
     "Cash flow from operating activities. Cash flow from investing activities. Cash "
     "flow from financing activities. Net increase in cash and cash equivalents."),
]


def seed(repos):
    ids = {}
    for tkr in ("RELIANCE", "TCS", "INFY"):
        ids[tkr] = repos.companies.upsert(Company(name=tkr, ticker=tkr)).company_id
    docs = {}
    for tkr in ids:
        docs[tkr] = repos.documents.upsert(DocumentMeta(
            company_id=ids[tkr], document_type="results_pdf",
            title=f"{tkr} Results", financial_year=2026,
        )).document_id
    chunks = []
    per_doc_idx = {t: 0 for t in ids}
    for tkr, section, topic, text in _CHUNKS:
        chunks.append(DocumentChunk(
            document_id=docs[tkr], company_id=ids[tkr], chunk_index=per_doc_idx[tkr],
            text=text, page_start=1, page_end=1, section=section,
            financial_year=2026, document_type="results_pdf", topic=topic,
        ))
        per_doc_idx[tkr] += 1
    repos.documents.add_chunks(chunks)
    repos.commit()
    return ids
