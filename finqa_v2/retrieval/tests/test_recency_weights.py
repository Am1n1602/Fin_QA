import tempfile
import unittest
from pathlib import Path

from finqa_v2.retrieval.recency_weights import DEFAULT_PATH, get_recency_decay


def _write(tmp: Path, text: str) -> Path:
    p = tmp / "recency.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class GetRecencyDecay(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_no_intent_is_a_no_op(self):
        self.assertEqual(get_recency_decay(None), 1.0)
        self.assertEqual(get_recency_decay(""), 1.0)

    def test_missing_file_is_a_no_op(self):
        self.assertEqual(get_recency_decay("numeric", path=self.tmp / "nope.yaml"), 1.0)

    def test_empty_file_is_a_no_op(self):
        p = _write(self.tmp, "")
        self.assertEqual(get_recency_decay("numeric", path=p), 1.0)

    def test_intent_specific_decay_applies(self):
        p = _write(self.tmp, "numeric: 0.85\n")
        self.assertEqual(get_recency_decay("numeric", path=p), 0.85)

    def test_unconfigured_intent_falls_back_to_default_key(self):
        p = _write(self.tmp, "default: 0.9\nnumeric: 0.85\n")
        self.assertEqual(get_recency_decay("narrative", path=p), 0.9)

    def test_unconfigured_intent_with_no_default_key_is_one(self):
        p = _write(self.tmp, "numeric: 0.85\n")
        self.assertEqual(get_recency_decay("narrative", path=p), 1.0)

    def test_real_config_file_loads_and_parses(self):
        self.assertEqual(get_recency_decay("numeric", path=DEFAULT_PATH), 0.85)
        self.assertEqual(get_recency_decay("causal", path=DEFAULT_PATH), 0.8)
        self.assertEqual(get_recency_decay("narrative", path=DEFAULT_PATH), 1.0)


if __name__ == "__main__":
    unittest.main()
