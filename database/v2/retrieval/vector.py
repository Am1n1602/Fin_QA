"""Dense vector index (§16). Uses faiss (IndexFlatIP over L2-normalized vectors =
cosine) when available, else a numpy brute-force fallback -- both exact. Building the
index needs an Embedder; the real one (SentenceTransformerEmbedder) pulls torch.
"""
from __future__ import annotations

import json
from pathlib import Path


class VectorUnavailable(RuntimeError):
    pass


class VectorIndex:
    def __init__(self, chunk_ids: list[int], matrix, *, faiss_index=None):
        self.chunk_ids = chunk_ids
        self._matrix = matrix          # np.ndarray (n, dim) float32, row-normalized
        self._faiss = faiss_index
        self.dim = int(matrix.shape[1]) if matrix is not None else 0

    @property
    def available(self) -> bool:
        return self._matrix is not None and len(self.chunk_ids) > 0

    # ------------------------------------------------------------------ #
    @classmethod
    def build(cls, repos, embedder, *, batch: int = 256, use_faiss: bool = True) -> "VectorIndex":
        import numpy as np

        rows = repos.connection.execute(
            "SELECT chunk_id, text FROM document_chunks ORDER BY chunk_id"
        ).fetchall()
        ids = [r["chunk_id"] for r in rows]
        vecs = []
        for i in range(0, len(rows), batch):
            vecs.append(embedder.encode([r["text"] for r in rows[i:i + batch]]))
        matrix = np.vstack(vecs).astype("float32") if vecs else np.zeros((0, 0), "float32")

        faiss_index = None
        if use_faiss and matrix.size:
            try:
                import faiss

                faiss_index = faiss.IndexFlatIP(matrix.shape[1])
                faiss_index.add(matrix)
            except Exception:
                faiss_index = None
        return cls(ids, matrix, faiss_index=faiss_index)

    # ------------------------------------------------------------------ #
    def search(self, query_vecs, k: int = 30) -> list[list[tuple[int, float]]]:
        import numpy as np

        if not self.available:
            return [[] for _ in range(len(query_vecs))]
        q = np.asarray(query_vecs, dtype="float32")
        if self._faiss is not None:
            scores, idxs = self._faiss.search(q, min(k, len(self.chunk_ids)))
        else:
            sims = q @ self._matrix.T
            idxs = np.argpartition(-sims, min(k, sims.shape[1] - 1), axis=1)[:, :k]
            idxs = np.take_along_axis(idxs, np.argsort(-np.take_along_axis(sims, idxs, axis=1), axis=1), axis=1)
            scores = np.take_along_axis(sims, idxs, axis=1)
        out = []
        for r in range(q.shape[0]):
            out.append([(self.chunk_ids[int(i)], float(s)) for i, s in zip(idxs[r], scores[r]) if int(i) >= 0])
        return out

    # ------------------------------------------------------------------ #
    def save(self, directory: str | Path) -> None:
        import numpy as np

        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        np.save(d / "matrix.npy", self._matrix)
        (d / "ids.json").write_text(json.dumps(self.chunk_ids))

    @classmethod
    def load(cls, directory: str | Path, *, use_faiss: bool = True) -> "VectorIndex":
        import numpy as np

        d = Path(directory)
        matrix = np.load(d / "matrix.npy")
        ids = json.loads((d / "ids.json").read_text())
        faiss_index = None
        if use_faiss and matrix.size:
            try:
                import faiss

                faiss_index = faiss.IndexFlatIP(matrix.shape[1])
                faiss_index.add(matrix.astype("float32"))
            except Exception:
                faiss_index = None
        return cls(ids, matrix.astype("float32"), faiss_index=faiss_index)
