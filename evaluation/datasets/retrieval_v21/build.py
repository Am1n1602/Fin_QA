"""Build the v2.1 retrieval benchmark dataset (§5).

    python -m evaluation.datasets.retrieval_v21.build [--target-total N] [--seed 21]
        [--v2-db PATH] [--out evaluation/datasets/retrieval_v21.json] [--check]

Every question is generated, then verified against the real corpus via `probe.probe()`
before being kept -- non-adversarial categories require >=1 real gold chunk; adversarial
and no_evidence items require the probe to come back *empty* (confirmed, not assumed).
`--check` re-validates an already-built file (every gold_chunk id still exists, category
counts still meet the §5.1 minimums) without regenerating it -- exit 1 on drift.
See docs/file-guide.md.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from evaluation.datasets.retrieval_v21 import categories as C
from evaluation.datasets.retrieval_v21.probe import distinct_document_types, probe
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "evaluation" / "datasets" / "retrieval_v21.json"

# §5.1's recommended minimum distribution -- sums to 380, comfortably clearing the >=300
# acceptance criterion while following the roadmap's own table rather than an arbitrary total.
QUOTAS: dict[str, int] = {
    "numeric": 40, "ratio": 30, "trend": 30, "narrative": 40, "causal": 40,
    "management_commentary": 25, "comparison": 30, "cross_document": 25,
    "multi_hop": 30, "table": 20, "segment": 20, "adversarial": 30, "no_evidence": 20,
}

_MAX_GOLD_PER_PROBE = 10


def _period_from_hits(hits, fallback: tuple[str, ...]) -> list[str]:
    years = sorted({h.financial_year for h in hits if h.financial_year})
    if years:
        return [f"FY{y}" for y in years]
    return list(fallback)


def _resolve_cross_document(conn, cand: C.Candidate) -> C.Candidate | None:
    spec = cand.probes[0]
    doc_types = distinct_document_types(conn, company_id=spec.company_id, keyword=spec.keyword)
    if len(doc_types) < 2:
        return None
    chosen = doc_types[:2]
    new_probes = tuple(
        C.ProbeSpec(document_types=(dt,), keyword=spec.keyword, company_id=spec.company_id)
        for dt in chosen
    )
    return C.Candidate(
        category=cand.category, question=cand.question, company_tickers=cand.company_tickers,
        period=cand.period, probes=new_probes, expect_hits=True, difficulty=cand.difficulty,
    )


def _verify(conn, cand: C.Candidate) -> tuple[bool, list, list[str]]:
    """Run every probe in `cand`; return (accepted, gold_hits, gold_sections)."""
    all_hits = []
    for spec in cand.probes:
        hits = probe(
            conn, company_id=spec.company_id, sections=list(spec.sections) if spec.sections else None,
            document_types=list(spec.document_types) if spec.document_types else None,
            topics=list(spec.topics) if spec.topics else None, keyword=spec.keyword,
            financial_year=spec.financial_year, limit=_MAX_GOLD_PER_PROBE,
        )
        all_hits.extend(hits)
    if cand.expect_hits:
        accepted = len(all_hits) > 0
    else:
        accepted = len(all_hits) == 0
    sections = sorted({h.section for h in all_hits if h.section})
    return accepted, all_hits, sections


def build(repos: SqliteRepositories, *, seed: int = 21, quotas: dict[str, int] = QUOTAS) -> list[dict]:
    conn = repos.connection
    companies = repos.companies.list(active=True)
    segments_by_company = {c.company_id: repos.segments.segments_for(c.company_id) for c in companies}
    rng = random.Random(seed)

    generators = {
        "numeric": C.gen_numeric(companies, rng),
        "ratio": C.gen_ratio(companies, rng),
        "trend": C.gen_trend(companies, rng),
        "narrative": C.gen_narrative(companies, rng),
        "causal": C.gen_causal(companies, rng),
        "management_commentary": C.gen_management_commentary(companies, rng),
        "comparison": C.gen_comparison(companies, rng),
        "cross_document": C.gen_cross_document(companies, rng),
        "multi_hop": C.gen_multi_hop(companies, segments_by_company, rng),
        "table": C.gen_table(companies, rng),
        "segment": C.gen_segment(companies, segments_by_company, rng),
        "adversarial": C.gen_adversarial(companies, rng),
        "no_evidence": C.gen_no_evidence(companies, rng),
    }

    records: list[dict] = []
    seen_questions: set[str] = set()
    counts: Counter = Counter()

    for category, gen in generators.items():
        quota = quotas.get(category, 0)
        for cand in gen:
            if counts[category] >= quota:
                break
            if cand.question in seen_questions:
                continue
            if cand.category == "cross_document":
                resolved = _resolve_cross_document(conn, cand)
                if resolved is None:
                    continue
                cand = resolved
            accepted, hits, sections = _verify(conn, cand)
            if not accepted:
                continue
            seen_questions.add(cand.question)
            counts[category] += 1
            gold_chunks = sorted({h.chunk_id for h in hits})
            rec = {
                "id": f"rv21-{category}-{counts[category]:04d}",
                "question": cand.question,
                "company": list(cand.company_tickers),
                "period": _period_from_hits(hits, cand.period),
                "intent": category,
                "gold_chunks": gold_chunks,
                "gold_sections": sections,
                "difficulty": cand.difficulty,
            }
            if cand.adversarial_type:
                rec["adversarial_type"] = cand.adversarial_type
            records.append(rec)

    return records


def check(path: Path, repos: SqliteRepositories, quotas: dict[str, int] = QUOTAS) -> bool:
    records = json.loads(path.read_text(encoding="utf-8"))
    conn = repos.connection
    ok = True
    if len(records) < 300:
        print(f"FAIL: only {len(records)} cases, need >=300")
        ok = False
    counts = Counter(r["intent"] for r in records)
    for cat, quota in quotas.items():
        if counts.get(cat, 0) < quota:
            print(f"FAIL: category {cat} has {counts.get(cat, 0)}, needs >= {quota}")
            ok = False
    all_ids = {r[0] for r in conn.execute("SELECT chunk_id FROM document_chunks")}
    for r in records:
        missing = [cid for cid in r["gold_chunks"] if cid not in all_ids]
        if missing:
            print(f"FAIL: {r['id']} references missing chunk_ids {missing}")
            ok = False
        if not r.get("intent"):
            print(f"FAIL: {r['id']} missing intent/query type")
            ok = False
    if ok:
        print(f"OK: {len(records)} cases, all gold_chunks resolve, all category minimums met.")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--out", type=Path, default=_OUT)
    ap.add_argument("--check", action="store_true", help="validate an existing --out file instead of building")
    args = ap.parse_args()

    repos = SqliteRepositories(args.v2_db)
    try:
        if args.check:
            ok = check(args.out, repos)
            return 0 if ok else 1
        records = build(repos, seed=args.seed)
    finally:
        repos.close()

    args.out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    counts = Counter(r["intent"] for r in records)
    print(f"wrote {len(records)} cases -> {args.out}")
    for cat in QUOTAS:
        print(f"  {cat:24s} {counts.get(cat, 0):4d}  (min {QUOTAS[cat]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
