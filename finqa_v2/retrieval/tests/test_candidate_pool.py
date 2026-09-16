import tempfile
import unittest
from pathlib import Path

from finqa_v2.retrieval.candidate_pool import DEFAULT_PATH, get_candidate_k


def _write(tmp: Path, text: str) -> Path:
    p = tmp / "pool.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class GetCandidateK(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_no_intent_returns_the_callers_default(self):
        self.assertEqual(get_candidate_k(None, default=30), 30)
        self.assertEqual(get_candidate_k("", default=30), 30)

    def test_missing_file_returns_the_callers_default(self):
        self.assertEqual(get_candidate_k("numeric", default=30, path=self.tmp / "nope.yaml"), 30)

    def test_empty_file_returns_the_callers_default(self):
        p = _write(self.tmp, "")
        self.assertEqual(get_candidate_k("numeric", default=30, path=p), 30)

    def test_configured_intent_overrides_the_default(self):
        p = _write(self.tmp, "numeric: 25\n")
        self.assertEqual(get_candidate_k("numeric", default=30, path=p), 25)

    def test_unconfigured_intent_falls_back_to_yaml_default_block(self):
        p = _write(self.tmp, "default: 40\nnumeric: 25\n")
        self.assertEqual(get_candidate_k("trend", default=30, path=p), 40)

    def test_unconfigured_intent_with_no_yaml_default_falls_back_to_callers_default(self):
        p = _write(self.tmp, "numeric: 25\n")
        self.assertEqual(get_candidate_k("trend", default=30, path=p), 30)

    def test_real_config_file_loads_and_parses(self):
        self.assertEqual(get_candidate_k("numeric", default=30, path=DEFAULT_PATH), 25)
        self.assertEqual(get_candidate_k("comparison", default=30, path=DEFAULT_PATH), 50)
        self.assertEqual(get_candidate_k("multi_hop", default=30, path=DEFAULT_PATH), 70)
        self.assertEqual(get_candidate_k("narrative", default=30, path=DEFAULT_PATH), 40)
        self.assertEqual(get_candidate_k("causal", default=30, path=DEFAULT_PATH), 40)  # via default:


if __name__ == "__main__":
    unittest.main()
