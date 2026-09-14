import unittest

from finqa_v2.retrieval.tests._fixture import seed
from finqa_v2.retrieval.text_builder import from_row
from finqa_v2.retrieval.vector import VectorIndex
from finqa_v2.sqlite import SqliteRepositories


class _RecordingEmbedder:
    """Records every text it was asked to encode; returns a trivial fixed-dim vector so
    VectorIndex.build's downstream numpy/faiss code has something valid to work with."""

    def __init__(self):
        self.seen: list[str] = []

    def encode(self, texts):
        import numpy as np

        self.seen.extend(texts)
        return np.zeros((len(texts), 4), dtype="float32")


class VectorIndexTextFn(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)

    def test_default_embeds_raw_text(self):
        embedder = _RecordingEmbedder()
        VectorIndex.build(self.repos, embedder, use_faiss=False)
        raw_texts = {r["text"] for r in
                    self.repos.connection.execute("SELECT text FROM document_chunks")}
        self.assertEqual(set(embedder.seen), raw_texts)

    def test_text_fn_receives_metadata_and_output_is_what_gets_embedded(self):
        embedder = _RecordingEmbedder()
        VectorIndex.build(self.repos, embedder, use_faiss=False, text_fn=from_row)
        # every embedded string should start with a "Company: " header (every fixture
        # chunk has a resolvable company) and still contain the original chunk text.
        raw_texts = [r["text"] for r in
                    self.repos.connection.execute("SELECT text FROM document_chunks")]
        self.assertEqual(len(embedder.seen), len(raw_texts))
        for enriched, raw in zip(embedder.seen, raw_texts):
            self.assertTrue(enriched.startswith("Company: "), enriched[:40])
            self.assertIn(raw, enriched)

    def test_text_fn_does_not_mutate_stored_chunk_text(self):
        embedder = _RecordingEmbedder()
        before = {r["chunk_id"]: r["text"] for r in
                 self.repos.connection.execute("SELECT chunk_id, text FROM document_chunks")}
        VectorIndex.build(self.repos, embedder, use_faiss=False, text_fn=from_row)
        after = {r["chunk_id"]: r["text"] for r in
                self.repos.connection.execute("SELECT chunk_id, text FROM document_chunks")}
        self.assertEqual(before, after)

    def test_chunk_ids_unaffected_by_text_fn(self):
        e1, e2 = _RecordingEmbedder(), _RecordingEmbedder()
        idx_raw = VectorIndex.build(self.repos, e1, use_faiss=False)
        idx_enriched = VectorIndex.build(self.repos, e2, use_faiss=False, text_fn=from_row)
        self.assertEqual(idx_raw.chunk_ids, idx_enriched.chunk_ids)


class VectorIndexGetVectors(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.idx = VectorIndex.build(self.repos, _RecordingEmbedder(), use_faiss=False)

    def test_returns_a_vector_per_known_id(self):
        vecs = self.idx.get_vectors(self.idx.chunk_ids[:2])
        self.assertEqual(set(vecs), set(self.idx.chunk_ids[:2]))
        for v in vecs.values():
            self.assertEqual(v.shape, (self.idx.dim,))

    def test_unknown_id_is_silently_omitted(self):
        real = self.idx.chunk_ids[0]
        vecs = self.idx.get_vectors([real, -999999])
        self.assertEqual(set(vecs), {real})

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(self.idx.get_vectors([]), {})

    def test_row_matches_the_matrix_row_for_that_chunk(self):
        cid = self.idx.chunk_ids[3]
        vec = self.idx.get_vectors([cid])[cid]
        row = self.idx.chunk_ids.index(cid)
        import numpy as np
        self.assertTrue(np.array_equal(vec, self.idx._matrix[row]))


if __name__ == "__main__":
    unittest.main()
