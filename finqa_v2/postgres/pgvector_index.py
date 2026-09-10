"""PgVectorIndex -- the same surface `HybridRetriever` expects from a `VectorIndex`
(`.available`, `.search(query_vecs, k)`), backed by `document_chunks.embedding` and
pgvector's cosine operator. Lets retrieval run entirely on Postgres (no faiss file).
"""
from __future__ import annotations


class PgVectorIndex:
    def __init__(self, pg_repos, *, dim: int = 384):
        self._raw = pg_repos._raw            # the psycopg connection
        self.dim = dim
        try:
            from pgvector.psycopg import register_vector

            register_vector(self._raw)
            self._n = self._raw.execute(
                "SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL"
            ).fetchone()[0]
        except Exception:
            self._n = 0

    @property
    def available(self) -> bool:
        return self._n > 0

    @property
    def chunk_ids(self):                     # HybridRetriever reads len() for logging only
        return range(self._n)

    def search(self, query_vecs, k: int = 30):
        import numpy as np

        q = np.asarray(query_vecs, dtype="float32")
        out = []
        with self._raw.cursor() as cur:
            for row_vec in q:
                cur.execute(
                    "SELECT chunk_id, 1 - (embedding <=> %s) AS score "
                    "FROM document_chunks WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> %s LIMIT %s",
                    (row_vec, row_vec, k),
                )
                out.append([(r[0], float(r[1])) for r in cur.fetchall()])
        return out
