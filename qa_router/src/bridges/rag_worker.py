"""

Run standalone only for debugging:
    python rag_worker.py --project-dir /path/to/rag --db-path ... --index-dir ...

Normally launched by rag_bridge.py -- never invoked directly.
"""

from __future__ import annotations

import argparse
import sys

from worker_protocol import install_protocol_stdout, run_worker_loop


def main() -> None:
    # MUST happen before importing anything from rag's src package --
    # Embedder/CrossEncoderReranker print progress messages on load.
    real_stdout = install_protocol_stdout()

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True, help="Path to rag/ (contains its own src/ package)")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--index-dir", required=True)
    parser.add_argument("--model-name", default="all-mpnet-base-v2")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--rerank-model", default="cross-encoder/ms-marco-MiniLM-L-6-v2")
    args = parser.parse_args()

    sys.path.insert(0, args.project_dir)

    from src.embedding.embedder import Embedder
    from src.indexing.faiss_index import DualFaissIndex
    from src.pipeline.retrieve import (
        _lexical_search,
        _phrase_overlap_search,
        _reciprocal_rank_fusion,
        _row_to_dict,
        hybrid_retrieve,
        reranked_retrieve,
        retrieve,
    )
    from src.storage.db import get_chunks_by_ids, get_connection

    embedder = Embedder(args.model_name, device=args.device)
    index = DualFaissIndex(dim=embedder.dim, index_dir=args.index_dir)

    _reranker_holder: dict = {}  # lazy -- only load the cross-encoder if it's actually needed

    def _reranker():
        if "reranker" not in _reranker_holder:
            from src.reranking.reranker import CrossEncoderReranker
            _reranker_holder["reranker"] = CrossEncoderReranker(args.rerank_model, device=args.device)
        return _reranker_holder["reranker"]

    def _expanded_retrieve(conn, query: str, expansions: list, k: int, company,
                            candidate_pool_per_variant: int, final_pool_size: int) -> list:

        all_queries = [query] + [e for e in expansions if e and e != query]
        vectors = embedder.embed(all_queries)  # one batched call, not N separate ones

        rankings = []
        for i, q_text in enumerate(all_queries):
            semantic_ids = [cid for cid, _ in index.search(vectors[i], k=candidate_pool_per_variant, company=company)]
            rankings.append(semantic_ids)
            rankings.append(_lexical_search(conn, q_text, company, top_n=candidate_pool_per_variant))
            rankings.append(_phrase_overlap_search(conn, q_text, company, top_n=candidate_pool_per_variant))

        fused = _reciprocal_rank_fusion(rankings)[:final_pool_size]
        if not fused:
            return []
        score_by_id = dict(fused)
        rows = get_chunks_by_ids(conn, [cid for cid, _ in fused])
        candidates = []
        for row in rows:
            d = _row_to_dict(row, score_by_id[row["id"]])
            d["id"] = row["id"]
            candidates.append(d)
        if not candidates:
            return []

        reranker = _reranker()
        texts = [c["text"] for c in candidates]
        n = len(texts)
        pairs = [(q, t) for q in all_queries for t in texts]  # all_queries[0] is the original question
        raw_scores = reranker.model.predict(pairs)  # one batched call across every (query variant, candidate) pair

        for idx, c in enumerate(candidates):
            per_query_scores = [float(raw_scores[q_i * n + idx]) for q_i in range(len(all_queries))]
            c["rerank_score"] = max(per_query_scores)
            c["rerank_score_vs_original_question"] = per_query_scores[0]  # kept for transparency/debugging

        candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
        return candidates[:k]

    def dispatch(command: str, params: dict):
        query = params["query"]
        k = params.get("k", 5)
        company = params.get("company")
        with get_connection(args.db_path) as conn:
            if command == "retrieve":
                return retrieve(conn, index, embedder, query=query, k=k, company=company)
            if command == "hybrid_retrieve":
                return hybrid_retrieve(conn, index, embedder, query=query, k=k, company=company)
            if command == "reranked_retrieve":
                return reranked_retrieve(conn, index, embedder, _reranker(), query=query, k=k, company=company)
            if command == "expanded_retrieve":
                return _expanded_retrieve(
                    conn, query, params.get("expansions", []), k, company,
                    candidate_pool_per_variant=params.get("candidate_pool_per_variant", 30),
                    final_pool_size=params.get("final_pool_size", 50),
                )
        raise ValueError(f"Unknown command: {command!r}")

    run_worker_loop(real_stdout, dispatch)


if __name__ == "__main__":
    main()