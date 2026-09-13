"""Consume the v2.1 retrieval benchmark's own failures and explain them (§6).

    python -m evaluation.error_analysis.analyzer \\
        --dataset evaluation/datasets/retrieval_v21.json --mode hybrid [--k 5] [--json OUT.json]

A "failure" is a non-adversarial/no_evidence case (real gold exists) whose gold chunk
doesn't appear in the top-`k` results under `--mode`. For each failure this classifies
*why*, using `classifier.classify()`, and reports the distribution -- the roadmap's own
"Top retrieval failures / WRONG_PERIOD 22% / ..." shape (§6).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from evaluation.error_analysis.classifier import ERROR_CLASSES, ChunkMeta, classify
from evaluation.run_retrieval_benchmark import load_dataset
from finqa_v2.retrieval.evaluate import build_retriever
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATASET = _ROOT / "evaluation" / "datasets" / "retrieval_v21.json"
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC = _ROOT / "database" / "data" / "finqa_v2_vec"
_RESULTS_DIR = _ROOT / "evaluation" / "results"

_ADVERSARIAL_INTENTS = {"adversarial", "no_evidence"}


def _company_id(repos, tickers: list[str] | None) -> tuple[int | None, bool]:
    """Returns (company_id_or_None, resolved). `resolved` is False only when a single
    ticker was given and it failed to resolve -- multi-ticker/no-ticker cases aren't a
    company-resolution failure by definition."""
    if not tickers or len(tickers) != 1:
        return None, True
    co = repos.companies.resolve(tickers[0])
    return (co.company_id, True) if co else (None, False)


def _superseded_map(conn: sqlite3.Connection, document_ids: set[int]) -> dict[int, bool]:
    if not document_ids:
        return {}
    placeholders = ",".join("?" for _ in document_ids)
    rows = conn.execute(
        f"SELECT document_id, is_superseded FROM documents WHERE document_id IN ({placeholders})",
        list(document_ids),
    ).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


def _gold_meta(conn: sqlite3.Connection, chunk_ids: list[int]) -> list[ChunkMeta]:
    if not chunk_ids:
        return []
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        "SELECT chunk_id, document_id, company_id, chunk_index, section, topic, financial_year "
        f"FROM document_chunks WHERE chunk_id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    sup = _superseded_map(conn, {r[1] for r in rows})
    return [
        ChunkMeta(chunk_id=r[0], document_id=r[1], company_id=r[2], chunk_index=r[3],
                  section=r[4], topic=r[5], financial_year=r[6], is_superseded=sup.get(r[1], False))
        for r in rows
    ]


def _hit_meta(conn: sqlite3.Connection, hits) -> list[ChunkMeta]:
    sup = _superseded_map(conn, {h.chunk.document_id for h in hits})
    return [
        ChunkMeta(chunk_id=h.chunk.chunk_id, document_id=h.chunk.document_id,
                  company_id=h.chunk.company_id, chunk_index=h.chunk.chunk_index,
                  section=h.chunk.section, topic=h.chunk.topic,
                  financial_year=h.chunk.financial_year, is_superseded=sup.get(h.chunk.document_id, False))
        for h in hits
    ]


def analyze(retriever, repos, records: list[dict], *, mode: str = "hybrid", k: int = 5,
           section_aware: bool = False) -> dict:
    conn = repos.connection
    counts: Counter = Counter()
    per_case = []
    n_scored = 0

    for rec in records:
        if rec["intent"] in _ADVERSARIAL_INTENTS or not rec["gold_chunks"]:
            continue
        n_scored += 1
        cid, resolved = _company_id(repos, rec.get("company"))
        filters = {"company_id": cid} if cid else None
        intent = rec["intent"] if section_aware else None
        hits = retriever.retrieve(rec["question"], k=max(k, 10), candidate_k=40,
                                  mode=mode, filters=filters, rerank=False, intent=intent)
        gold_ids = set(rec["gold_chunks"])
        top = hits[:k]
        if any(h.chunk.chunk_id in gold_ids for h in top):
            continue  # not a failure

        lexical_found = vector_found = None
        if mode == "hybrid":
            for other_mode, flag_name in (("lexical", "lexical_found"), ("vector", "vector_found")):
                if other_mode in retriever.modes:
                    other_hits = retriever.retrieve(rec["question"], k=k, candidate_k=40,
                                                    mode=other_mode, filters=filters, rerank=False,
                                                    intent=intent)
                    found = any(h.chunk.chunk_id in gold_ids for h in other_hits)
                    if flag_name == "lexical_found":
                        lexical_found = found
                    else:
                        vector_found = found

        gold_meta = _gold_meta(conn, rec["gold_chunks"])
        top_meta = _hit_meta(conn, top)
        error_class = classify(
            intent=rec["intent"], had_company=bool(rec.get("company")), company_resolved=resolved,
            gold=gold_meta, top_hits=top_meta, lexical_found=lexical_found, vector_found=vector_found,
        )
        counts[error_class] += 1
        per_case.append({"id": rec["id"], "intent": rec["intent"], "error_class": error_class})

    n_failures = sum(counts.values())
    return {
        "mode": mode, "k": k, "n_scored": n_scored, "n_failures": n_failures,
        "failure_rate": round(n_failures / n_scored, 4) if n_scored else None,
        "distribution": {
            cls: {"count": counts.get(cls, 0),
                 "pct": round(100 * counts.get(cls, 0) / n_failures, 1) if n_failures else 0.0}
            for cls in ERROR_CLASSES
        },
        "per_case": per_case,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--bm25", type=Path, default=_BM25)
    ap.add_argument("--vector-dir", type=Path, default=_VEC)
    ap.add_argument("--mode", default="hybrid")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--section-aware", action="store_true",
                    help="pass each case's own intent to retrieve() for §15 section weighting")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")

    records = load_dataset(args.dataset)
    repos = SqliteRepositories(args.v2_db)
    try:
        retriever = build_retriever(repos, bm25_path=args.bm25, vector_dir=args.vector_dir)
        report = analyze(retriever, repos, records, mode=args.mode, k=args.k,
                         section_aware=args.section_aware)
    finally:
        repos.close()

    print(f"mode={report['mode']}  k={report['k']}  scored={report['n_scored']}  "
          f"failures={report['n_failures']}  failure_rate={report['failure_rate']}")
    print()
    print("Top retrieval failures\n")
    ranked = sorted(report["distribution"].items(), key=lambda kv: kv[1]["count"], reverse=True)
    for cls, d in ranked:
        if d["count"]:
            print(f"{cls:26s} {d['pct']:5.1f}%  ({d['count']})")
    zero_classes = [cls for cls, d in ranked if not d["count"]]
    if zero_classes:
        print(f"\n(0 occurrences: {', '.join(zero_classes)})")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
