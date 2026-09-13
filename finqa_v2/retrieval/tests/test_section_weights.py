import tempfile
import unittest
from pathlib import Path

from finqa_v2.retrieval.section_weights import DEFAULT_PATH, get_weight


def _write(tmp: Path, text: str) -> Path:
    p = tmp / "weights.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class GetWeight(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_no_section_is_a_no_op(self):
        self.assertEqual(get_weight("causal", None), 1.0)
        self.assertEqual(get_weight("causal", ""), 1.0)

    def test_no_intent_still_applies_global(self):
        p = _write(self.tmp, "global:\n  cover_letter: 0.3\n")
        self.assertEqual(get_weight(None, "cover_letter", path=p), 0.3)

    def test_missing_file_is_a_no_op(self):
        self.assertEqual(get_weight("causal", "mda", path=self.tmp / "nope.yaml"), 1.0)

    def test_empty_file_is_a_no_op(self):
        p = _write(self.tmp, "")
        self.assertEqual(get_weight("causal", "mda", path=p), 1.0)

    def test_unconfigured_section_defaults_to_one(self):
        p = _write(self.tmp, "causal:\n  mda: 1.5\n")
        self.assertEqual(get_weight("causal", "risk_factors", path=p), 1.0)

    def test_intent_specific_weight_applies(self):
        p = _write(self.tmp, "causal:\n  mda: 1.5\n")
        self.assertEqual(get_weight("causal", "mda", path=p), 1.5)

    def test_intent_weight_does_not_leak_to_other_intents(self):
        p = _write(self.tmp, "causal:\n  mda: 1.5\n")
        self.assertEqual(get_weight("trend", "mda", path=p), 1.0)

    def test_global_and_intent_weights_multiply(self):
        p = _write(self.tmp, "global:\n  mda: 2.0\ncausal:\n  mda: 1.5\n")
        self.assertEqual(get_weight("causal", "mda", path=p), 3.0)

    def test_real_config_file_loads_and_parses(self):
        # the actual shipped config, not a fixture -- catches a YAML syntax error early.
        self.assertEqual(get_weight("causal", "mda", path=DEFAULT_PATH), 1.5)
        self.assertEqual(get_weight(None, "cover_letter", path=DEFAULT_PATH), 0.3)
        self.assertEqual(get_weight("numeric", "nonexistent_section", path=DEFAULT_PATH), 1.0)


if __name__ == "__main__":
    unittest.main()
