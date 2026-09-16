from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np


def _company_key(company: str) -> str:
    return company.strip().upper()


class DualFaissIndex:
    def __init__(self, dim: int, index_dir: str | Path):
        self.dim = dim
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._company_indices: dict[str, faiss.IndexIDMap] = {}
        self._global_index: faiss.IndexIDMap | None = None

    # --- index creation/loading ---

    def _new_index(self) -> faiss.IndexIDMap:
        return faiss.IndexIDMap(faiss.IndexFlatIP(self.dim))

    def _company_path(self, company: str) -> Path:
        return self.index_dir / f"company_{_company_key(company)}.faiss"

    def _global_path(self) -> Path:
        return self.index_dir / "global.faiss"

    def _load_and_check(self, path: Path) -> faiss.IndexIDMap:

        index = faiss.read_index(str(path))
        if index.d != self.dim:
            raise ValueError(
                f"Dimension mismatch loading {path}: saved index has dim={index.d}, "
                f"but this run is configured for dim={self.dim} (likely a different "
                f"embedding model than whatever built this index). Delete the old "
                f"index files under {self.index_dir} and re-ingest with the new model "
                f"-- indices from different models are never compatible."
            )
        return index

    def _get_company_index(self, company: str) -> faiss.IndexIDMap:
        key = _company_key(company)
        if key not in self._company_indices:
            path = self._company_path(company)
            self._company_indices[key] = self._load_and_check(path) if path.exists() else self._new_index()
        return self._company_indices[key]

    def _get_global_index(self) -> faiss.IndexIDMap:
        if self._global_index is None:
            path = self._global_path()
            self._global_index = self._load_and_check(path) if path.exists() else self._new_index()
        return self._global_index

    # --- mutation ---

    def add(self, company: str, ids: list[int], vectors: np.ndarray):
        """Adds the same vectors to both the company-specific index and the
        global index, under the given ids (document_chunks.id values)."""
        if len(ids) != vectors.shape[0]:
            raise ValueError(f"ids length ({len(ids)}) != vectors row count ({vectors.shape[0]})")
        if vectors.shape[1] != self.dim:
            raise ValueError(f"vector dim ({vectors.shape[1]}) != index dim ({self.dim})")

        id_arr = np.array(ids, dtype=np.int64)

        company_index = self._get_company_index(company)
        company_index.add_with_ids(vectors, id_arr)

        global_index = self._get_global_index()
        global_index.add_with_ids(vectors, id_arr)

    # --- search ---

    def search(self, query_vector: np.ndarray, k: int = 10, company: str | None = None):
        if query_vector.ndim == 1:
            query_vector = query_vector.reshape(1, -1)
        query_vector = query_vector.astype(np.float32)

        index = self._get_company_index(company) if company else self._get_global_index()
        if index.ntotal == 0:
            return []

        scores, ids = index.search(query_vector, min(k, index.ntotal))
        results = []
        for score, chunk_id in zip(scores[0], ids[0]):
            if chunk_id == -1:  # FAISS pads with -1 if fewer than k results exist
                continue
            results.append((int(chunk_id), float(score)))
        return results

    # --- persistence ---

    def save(self):
        for key, index in self._company_indices.items():
            faiss.write_index(index, str(self.index_dir / f"company_{key}.faiss"))
        if self._global_index is not None:
            faiss.write_index(self._global_index, str(self._global_path()))
            
        manifest = {
            "dim": self.dim,
            "companies": {
                key: int(idx.ntotal) for key, idx in self._company_indices.items()
            },
            "global_total": int(self._global_index.ntotal) if self._global_index else 0,
        }
        with open(self.index_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)