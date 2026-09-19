"""VectorIndex.build's optional metadata-enriched text_fn hook."""
from __future__ import annotations

import unittest

from finqa_v2.retrieval.embed import HashEmbedder
from finqa_v2.retrieval.tests._fixture import seed
from finqa_v2.retrieval.text_builder import from_row
from finqa_v2.retrieval.vector import VectorIndex
from finqa_v2.sqlite import SqliteRepositories


class _RecordingEmbedder:
    """Wraps a real embedder and records the exact strings it was asked to embed."""

    def __init__(self, dim=8):
        self._inner = HashEmbedder(dim=dim)
        self.seen: list[str] = []

    def encode(self, texts):
        self.seen.extend(texts)
        return self._inner.encode(texts)


class TestTextFnHook(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.rows = self.repos.connection.execute(
            "SELECT chunk_id, text FROM document_chunks ORDER BY chunk_id"
        ).fetchall()

    def test_none_is_a_byte_for_byte_noop(self):
        rec = _RecordingEmbedder()
        idx = VectorIndex.build(self.repos, rec, use_faiss=False)
        self.assertEqual(rec.seen, [r["text"] for r in self.rows])
        self.assertEqual(idx.chunk_ids, [r["chunk_id"] for r in self.rows])

    def test_text_fn_enriches_embedder_input_without_touching_chunk_text_or_ids(self):
        rec = _RecordingEmbedder()
        idx = VectorIndex.build(self.repos, rec, use_faiss=False, text_fn=from_row)
        raw_texts = [r["text"] for r in self.rows]
        self.assertNotEqual(rec.seen, raw_texts)
        # each embedded string still ends with the chunk's real, unmutated text
        self.assertTrue(all(seen.endswith(raw) for seen, raw in zip(rec.seen, raw_texts)))
        # a header (company/FY/section) was actually prepended
        self.assertTrue(any(s.startswith(("RELIANCE", "TCS", "INFY")) for s in rec.seen))
        # document_chunks.text on disk and chunk ordering/ids are unaffected either way
        self.assertEqual(idx.chunk_ids, [r["chunk_id"] for r in self.rows])
        still_raw = self.repos.connection.execute(
            "SELECT text FROM document_chunks ORDER BY chunk_id"
        ).fetchall()
        self.assertEqual([r["text"] for r in still_raw], raw_texts)


if __name__ == "__main__":
    unittest.main()
