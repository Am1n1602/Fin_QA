import tempfile
import unittest
from pathlib import Path

from finqa_v2.retrieval.fusion_weights import DEFAULT_PATH, get_fusion_weights


def _write(tmp: Path, text: str) -> Path:
    p = tmp / "weights.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class GetFusionWeights(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_missing_file_is_plain_rrf(self):
        self.assertEqual(get_fusion_weights("causal", path=self.tmp / "nope.yaml"), (1.0, 1.0))

    def test_empty_file_is_plain_rrf(self):
        p = _write(self.tmp, "")
        self.assertEqual(get_fusion_weights("causal", path=p), (1.0, 1.0))

    def test_no_intent_falls_back_to_default_block(self):
        p = _write(self.tmp, "default:\n  lexical: 2.0\n  vector: 0.5\n")
        self.assertEqual(get_fusion_weights(None, path=p), (2.0, 0.5))

    def test_unconfigured_intent_falls_back_to_default_block(self):
        p = _write(self.tmp, "default:\n  lexical: 2.0\n  vector: 0.5\ncausal:\n  lexical: 3.0\n  vector: 1.0\n")
        self.assertEqual(get_fusion_weights("trend", path=p), (2.0, 0.5))

    def test_intent_specific_weight_overrides_default(self):
        p = _write(self.tmp, "default:\n  lexical: 1.0\n  vector: 1.0\ncausal:\n  lexical: 0.7\n  vector: 1.3\n")
        self.assertEqual(get_fusion_weights("causal", path=p), (0.7, 1.3))

    def test_no_default_block_and_no_match_is_plain_rrf(self):
        p = _write(self.tmp, "causal:\n  lexical: 0.7\n  vector: 1.3\n")
        self.assertEqual(get_fusion_weights("trend", path=p), (1.0, 1.0))

    def test_real_config_file_loads_and_defaults_to_plain_rrf(self):
        # confirms the real YAML parses and is a true no-op for every intent it doesn't
        # explicitly override.
        self.assertEqual(get_fusion_weights(None, path=DEFAULT_PATH), (1.0, 1.0))
        self.assertEqual(get_fusion_weights("causal", path=DEFAULT_PATH), (1.0, 1.0))

    def test_real_config_benchmark_earned_overrides(self):
        # the §16 A/B's actual winning weights -- see fusion_weights.yaml's own comment for
        # the per-category Recall@5 evidence behind each one.
        self.assertEqual(get_fusion_weights("management_commentary", path=DEFAULT_PATH), (2.0, 0.5))
        self.assertEqual(get_fusion_weights("trend", path=DEFAULT_PATH), (2.5, 0.3))
        self.assertEqual(get_fusion_weights("multi_hop", path=DEFAULT_PATH), (0.7, 1.3))
        self.assertEqual(get_fusion_weights("table", path=DEFAULT_PATH), (0.2, 3.0))


if __name__ == "__main__":
    unittest.main()
