"""Financial-aware chunking benchmark (§9): current 900/120 packing vs 500/750/1200 char
targets, on the same handful of real filings, using Recall@5 as the acceptance signal.

Re-chunking + re-indexing the full 578-document corpus for every candidate config is
prohibitively slow (~57min for one full backfill pass, per docs/file-guide.md) for a
category Phase 2's error analysis found responsible for only 2-7% of retrieval failures
(CHUNK_BOUNDARY) -- so this benchmarks a real sample of companies/documents instead, not
the full corpus. Extraction + section-detection (the slow, target-independent steps) run
ONCE per sampled PDF and are reused across every target-size config; only the packing step
(`finqa_v2.documents.chunk.chunk_document`, itself target-independent-refactor-free --
already accepts `target`/`overlap`) and the resulting re-chunk/re-index/re-gold/re-benchmark
are repeated per config.

Each config gets its OWN freshly-generated `retrieval_v21`-style gold set (via
`evaluation.datasets.retrieval_v21.build.build()`, smaller quotas) rather than reusing the
production `retrieval_v21.json`'s gold_chunks -- those chunk_ids are tied to the *current*
900-char chunking and would not exist at all under a different target size. Comparing
Recall@5 across configs, each scored against its own honestly-probed gold, is the correct
apples-to-apples methodology here.

    python -m evaluation.benchmarks.chunking [--json evaluation/results/chunking_v21.json]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from finqa_v2.documents.chunk import chunk_document
from finqa_v2.documents.extract import extract_pages
from finqa_v2.documents.pipeline import document_type_of, period_and_fy, title_from_filename
from finqa_v2.documents.sections import detect_sections
from finqa_v2.models import Company, DocumentMeta, Segment
from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[2]
_RAW = _ROOT / "data_extraction" / "data" / "raw"

# A real, varied sample -- not the full 50-company universe, but real filings from real
# companies across sectors and document types (results PDFs + transcripts).
SAMPLE_TICKERS = ["TCS", "RELIANCE", "HDFCBANK", "INFY", "ITC", "TATASTEEL"]
PDFS_PER_TICKER = 3

CONFIGS = {
    "500": {"target": 500, "overlap": 70},
    "750": {"target": 750, "overlap": 100},
    "900_current": {"target": 900, "overlap": 120},
    "1200": {"target": 1200, "overlap": 160},
}

# A handful of categories most sensitive to chunk boundaries -- not the full 13, since a
# 6-company sample can't hit the production quotas, and this experiment is comparative
# (config vs config), not the production dataset.
SAMPLE_QUOTAS = {"numeric": 8, "ratio": 6, "causal": 8, "narrative": 8, "segment": 5, "table": 5}


def _sample_pdfs(*, tickers: list[str] | None = None,
                 pdfs_per_ticker: int | None = None) -> list[tuple[str, Path]]:
    """[(ticker, pdf_path), ...] -- a few real PDFs per sampled ticker."""
    tickers = tickers if tickers is not None else SAMPLE_TICKERS
    pdfs_per_ticker = pdfs_per_ticker if pdfs_per_ticker is not None else PDFS_PER_TICKER
    out = []
    for ticker in tickers:
        d = _RAW / ticker
        if not d.exists():
            continue
        pdfs = sorted(d.glob("*.pdf"))[:pdfs_per_ticker]
        out.extend((ticker, p) for p in pdfs)
    return out


def _extract_all(pdfs: list[tuple[str, Path]]) -> list[dict]:
    """Extraction + section detection ONCE per PDF -- target-independent, reused by
    every config below."""
    extracted = []
    for ticker, path in pdfs:
        result = extract_pages(path, detect_tables=True)
        if not result.ok:
            print(f"  [skip] {ticker}/{path.name}: {result.error}")
            continue
        title = title_from_filename(path.name)
        spans = detect_sections(result.pages)
        _, fy = period_and_fy(title, filename=path.name)
        extracted.append({
            "ticker": ticker, "path": path, "title": title,
            "document_type": document_type_of(title), "financial_year": fy,
            "pages": result.pages, "spans": spans,
        })
    return extracted


def _build_scratch_db(extracted: list[dict], source_repos, *, target: int, overlap: int,
                      out_path: Path) -> SqliteRepositories:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)
    scratch = SqliteRepositories(out_path)
    tickers = {e["ticker"] for e in extracted}
    company_ids: dict[str, int] = {}
    for ticker in tickers:
        co = source_repos.companies.resolve(ticker)
        new_co = scratch.companies.upsert(Company(
            name=co.name, ticker=co.ticker, exchange=co.exchange, sector=co.sector,
            industry=co.industry,
        ))
        company_ids[ticker] = new_co.company_id
        for seg in source_repos.segments.segments_for(co.company_id):
            scratch.segments.upsert_segment(Segment(
                company_id=new_co.company_id, name=seg.name, slug=seg.slug,
            ))

    for e in extracted:
        cid = company_ids[e["ticker"]]
        doc = scratch.documents.upsert(DocumentMeta(
            company_id=cid, document_type=e["document_type"], title=e["title"],
            financial_year=e["financial_year"],
        ))
        seg_slugs = [s.slug for s in scratch.segments.segments_for(cid)]
        chunks = chunk_document(
            e["pages"], e["spans"], document_id=doc.document_id, company_id=cid,
            financial_year=e["financial_year"], document_type=e["document_type"],
            segment_slugs=seg_slugs, target=target, overlap=overlap,
        )
        scratch.documents.add_chunks(chunks)
    scratch.commit()
    return scratch


def run(*, out_dir: Path | None = None, configs: dict | None = None,
       tickers: list[str] | None = None, pdfs_per_ticker: int | None = None,
       quotas: dict | None = None) -> dict:
    out_dir = out_dir or (_ROOT / "database" / "data" / "chunking_bench")
    configs = configs if configs is not None else CONFIGS
    quotas = quotas if quotas is not None else SAMPLE_QUOTAS
    source_repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
    try:
        pdfs = _sample_pdfs(tickers=tickers, pdfs_per_ticker=pdfs_per_ticker)
        print(f"sample: {len(pdfs)} PDFs across {len(tickers or SAMPLE_TICKERS)} tickers")
        extracted = _extract_all(pdfs)
        print(f"extracted {len(extracted)} documents (extraction cached, reused across configs)")

        from evaluation.datasets.retrieval_v21.build import build as build_gold
        from evaluation.run_retrieval_benchmark import run_mode
        from finqa_v2.retrieval.evaluate import build_retriever

        results = {}
        for name, cfg in configs.items():
            db_path = out_dir / f"finqa_v2_chunking_{name}.db"
            scratch = _build_scratch_db(extracted, source_repos, target=cfg["target"],
                                        overlap=cfg["overlap"], out_path=db_path)
            try:
                n_chunks = scratch.connection.execute(
                    "SELECT COUNT(*) FROM document_chunks").fetchone()[0]
                gold = build_gold(scratch, seed=21, quotas=quotas)
                bm25_path = out_dir / f"bm25_{name}.pkl"
                bm25 = BM25Index.build(scratch)
                bm25.save(bm25_path)
                retriever = build_retriever(scratch, bm25_path=bm25_path, vector_dir=out_dir / "novec")
                report = run_mode(retriever, scratch, gold, "lexical", filter_company=True)
                results[name] = {
                    "target": cfg["target"], "overlap": cfg["overlap"], "n_chunks": n_chunks,
                    "n_gold": len(gold), "recall@5": report.get("recall@5"),
                    "recall@10": report.get("recall@10"), "mrr": report.get("mrr"),
                    "ndcg@5": report.get("ndcg@5"), "p50_ms": report.get("p50_ms"),
                }
                print(f"  {name:12s} chunks={n_chunks:4d} gold={len(gold):3d} "
                      f"R@5={results[name]['recall@5']} MRR={results[name]['mrr']}")
            finally:
                scratch.close()
        return results
    finally:
        source_repos.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    results = run()
    print()
    print(f"{'config':14s} {'target':>7s} {'chunks':>7s} {'R@5':>7s} {'R@10':>7s} {'MRR':>7s} {'nDCG@5':>7s}")
    for name, r in results.items():
        print(f"{name:14s} {r['target']:>7d} {r['n_chunks']:>7d} {r['recall@5']!s:>7s} "
              f"{r['recall@10']!s:>7s} {r['mrr']!s:>7s} {r['ndcg@5']!s:>7s}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"sample_tickers": SAMPLE_TICKERS, "results": results}, indent=2),
                             encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
