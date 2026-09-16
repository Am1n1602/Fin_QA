"""Projection to 100 / 250 / 500 companies (§43).

We have one real data point (the NIFTY-50 dataset), so this is an explicit model, not a
measurement. Per-dimension growth assumptions:

* facts / segment_facts / share_prices / documents / chunks / sources / db bytes /
  index bytes  -- LINEAR in company count. Each company's data is independent; nothing
  cross-joins companies at ingest.
* per-query latency (engine, retrieval-with-company-filter, full deterministic pipeline)
  -- ~CONSTANT. `build_period_records` is O(one company's facts); `compare_companies` is
  O(k named companies); the retrieval metadata pre-filter (§16 step 1) bounds BM25/vector
  scoring to one company's chunks. None of these grow with the universe.
* LLM cost / query -- CONSTANT (planner + synthesis over one question's evidence).
  Total spend scales with query *volume*, not company count.

So the architecture scales linearly in storage and flat in per-query latency. The first
thing to break is an operational one: the BM25 index is a single in-RAM pickle rebuilt
whole on every ingest.
"""
from __future__ import annotations

_LINEAR_COUNTS = ("facts", "segment_facts", "share_prices", "documents", "chunks", "sources")
_LINEAR_BYTES = ("db_bytes", "bm25_index_bytes", "vector_index_bytes")

# operational thresholds -> what to do when crossed
_THRESHOLDS = [
    ("bm25_ram_mb", 1500,
     "BM25 is one in-RAM pickle rebuilt in full on every ingest -- move lexical search to "
     "Postgres full-text search (incremental, on-disk). This is Phase 17."),
    ("vector_ram_mb", 3500,
     "the flat float32 vector matrix no longer fits comfortably in the 4 GB GPU / RAM -- "
     "switch faiss to an IVF/HNSW index, or use pgvector's ANN index (Phase 17)."),
    ("db_gb", 5.0,
     "SQLite is still functional but a single-writer file is now the ceiling -- migrate to "
     "PostgreSQL + pgvector (Phase 17); the repository Protocols already isolate this."),
]


def project(footprint: dict, benchmark: dict | None = None,
            targets: tuple[int, ...] = (100, 250, 500)) -> dict:
    base_n = footprint["companies"]
    pc = footprint["per_company"]
    pipe_p50 = None
    if benchmark:
        pipe_p50 = benchmark.get("pipeline_overall", {}).get("p50_of_p50_ms")

    rows = []
    for n in (base_n, *targets):
        r = {"companies": n, "scale_x": round(n / base_n, 1)}
        for c in _LINEAR_COUNTS:
            r[c] = int(round(pc[c] * n))
        r["db_gb"] = round(pc["db_bytes"] * n / 1e9, 2)
        r["bm25_ram_mb"] = round(pc["bm25_index_bytes"] * n / 1e6, 1)
        r["vector_ram_mb"] = round(pc["vector_index_bytes"] * n / 1e6, 1)
        r["pipeline_p50_ms_est"] = pipe_p50            # flat -- see module docstring
        rows.append(r)

    at_max = rows[-1]
    crossed = [{"metric": m, "value": at_max[m], "threshold": t, "action": a}
               for m, t, a in _THRESHOLDS if at_max.get(m, 0) >= t]
    return {
        "base_companies": base_n,
        "growth_model": "linear storage, constant per-query latency (metadata pre-filter)",
        "rows": rows,
        "thresholds_crossed_at_max": crossed,
        "verdict": (
            "Conceptual architecture holds to 500 with no redesign. "
            + ("First operational limit: " + crossed[0]["action"]
               if crossed else
               "No operational threshold is crossed at 500 on this hardware; "
               "Postgres + pgvector (Phase 17) is still the right move for concurrency, "
               "incremental indexing and multi-writer, not raw size.")
        ),
    }


def render(p: dict) -> str:
    lines = [f"projection from {p['base_companies']} companies -- {p['growth_model']}",
             f"  {'N':>5} {'facts':>10} {'chunks':>10} {'db GB':>8} {'bm25 MB':>9} {'vec MB':>9} {'pipe p50':>9}"]
    for r in p["rows"]:
        lines.append(f"  {r['companies']:>5} {r['facts']:>10,} {r['chunks']:>10,} "
                     f"{r['db_gb']:>8} {r['bm25_ram_mb']:>9} {r['vector_ram_mb']:>9} "
                     f"{str(r['pipeline_p50_ms_est']) + ' ms':>9}")
    if p["thresholds_crossed_at_max"]:
        lines.append("  thresholds crossed at 500:")
        for c in p["thresholds_crossed_at_max"]:
            lines.append(f"    {c['metric']} = {c['value']} (> {c['threshold']}) -> {c['action']}")
    lines.append("  verdict: " + p["verdict"])
    return "\n".join(lines)
