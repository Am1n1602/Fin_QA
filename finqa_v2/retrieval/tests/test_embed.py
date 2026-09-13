import unittest

from finqa_v2.retrieval.embed import SentenceTransformerEmbedder


class SentenceTransformerEmbedderConstruction(unittest.TestCase):
    """No network/model load here -- just the constructor/attribute surface added for
    the Phase 3 embedding-model benchmark (larger models need a smaller batch size on
    limited VRAM; jina-embeddings-v3 needs trust_remote_code)."""

    def test_defaults_unchanged(self):
        e = SentenceTransformerEmbedder()
        self.assertEqual(e.model_name, "all-mpnet-base-v2")
        self.assertEqual(e.device, "cpu")
        self.assertEqual(e.batch_size, 32)
        self.assertFalse(e.trust_remote_code)

    def test_custom_batch_size_and_trust_remote_code(self):
        e = SentenceTransformerEmbedder("BAAI/bge-m3", device="cuda", batch_size=8,
                                        trust_remote_code=True)
        self.assertEqual(e.batch_size, 8)
        self.assertTrue(e.trust_remote_code)

    def test_model_not_loaded_until_first_use(self):
        e = SentenceTransformerEmbedder("BAAI/bge-m3")
        self.assertIsNone(e._model)


if __name__ == "__main__":
    unittest.main()
