"""SentenceTransformerEmbedder construction knobs -- no real model load (no network)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from finqa_v2.retrieval.embed import HashEmbedder, SentenceTransformerEmbedder


class TestHashEmbedder(unittest.TestCase):
    def test_deterministic_and_normalized(self):
        e = HashEmbedder(dim=32)
        v1 = e.encode(["hello world"])
        v2 = e.encode(["hello world"])
        self.assertTrue((v1 == v2).all())
        self.assertAlmostEqual(float((v1[0] ** 2).sum()), 1.0, places=5)


class TestSentenceTransformerEmbedderConstruction(unittest.TestCase):
    @patch("sentence_transformers.SentenceTransformer")
    def test_forces_safetensors_and_passes_through_knobs(self, mock_cls):
        mock_cls.return_value = MagicMock()
        e = SentenceTransformerEmbedder("BAAI/bge-m3", device="cuda",
                                        batch_size=16, trust_remote_code=True)
        e._get()
        mock_cls.assert_called_once_with(
            "BAAI/bge-m3", device="cuda", trust_remote_code=True,
            model_kwargs={"use_safetensors": True},
        )

    @patch("sentence_transformers.SentenceTransformer")
    def test_defaults_are_off_and_model_loaded_once(self, mock_cls):
        mock_cls.return_value = MagicMock()
        e = SentenceTransformerEmbedder()
        e._get()
        e._get()
        mock_cls.assert_called_once_with(
            "all-mpnet-base-v2", device="cpu", trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )

    @patch("sentence_transformers.SentenceTransformer")
    def test_encode_uses_configured_batch_size(self, mock_cls):
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 4), dtype="float32")
        mock_cls.return_value = mock_model
        e = SentenceTransformerEmbedder(batch_size=8)
        e.encode(["x"])
        _, kwargs = mock_model.encode.call_args
        self.assertEqual(kwargs["batch_size"], 8)


if __name__ == "__main__":
    unittest.main()
