import tempfile
import unittest
from pathlib import Path

from finqa_v2.retrieval.section_weights import (
    DEFAULT_PATH,
    get_topic_weight,
    get_weight,
    list_weighted_sections,
)


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


class ListWeightedSections(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_no_intent_is_empty(self):
        self.assertEqual(list_weighted_sections(None), [])
        self.assertEqual(list_weighted_sections(""), [])

    def test_missing_file_is_empty(self):
        self.assertEqual(list_weighted_sections("causal", path=self.tmp / "nope.yaml"), [])

    def test_only_sections_above_min_weight(self):
        p = _write(self.tmp, "causal:\n  mda: 1.5\n  earnings_call: 1.0\n  risk_factors: 0.5\n")
        self.assertEqual(list_weighted_sections("causal", path=p), ["mda"])

    def test_sorted_and_deduped_by_construction(self):
        p = _write(self.tmp, "numeric:\n  notes: 1.1\n  balance_sheet: 1.2\n  financial_results: 1.4\n")
        self.assertEqual(list_weighted_sections("numeric", path=p),
                         ["balance_sheet", "financial_results", "notes"])

    def test_real_config_matches_get_weight(self):
        hints = list_weighted_sections("causal", path=DEFAULT_PATH)
        self.assertIn("mda", hints)
        for section in hints:
            self.assertGreater(get_weight("causal", section, path=DEFAULT_PATH), 1.0)


class GetTopicWeight(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def test_no_topic_is_a_no_op(self):
        self.assertEqual(get_topic_weight("numeric", None), 1.0)
        self.assertEqual(get_topic_weight("numeric", ""), 1.0)

    def test_missing_file_is_a_no_op(self):
        self.assertEqual(get_topic_weight("numeric", "table", path=self.tmp / "nope.yaml"), 1.0)

    def test_no_topics_block_is_a_no_op(self):
        p = _write(self.tmp, "causal:\n  mda: 1.5\n")
        self.assertEqual(get_topic_weight("numeric", "table", path=p), 1.0)

    def test_intent_specific_topic_weight_applies(self):
        p = _write(self.tmp, "topics:\n  numeric:\n    table: 1.6\n")
        self.assertEqual(get_topic_weight("numeric", "table", path=p), 1.6)

    def test_topic_weight_does_not_leak_to_other_intents(self):
        p = _write(self.tmp, "topics:\n  numeric:\n    table: 1.6\n")
        self.assertEqual(get_topic_weight("ratio", "table", path=p), 1.0)

    def test_topics_global_and_intent_multiply(self):
        p = _write(self.tmp, "topics:\n  global:\n    table: 2.0\n  numeric:\n    table: 1.5\n")
        self.assertEqual(get_topic_weight("numeric", "table", path=p), 3.0)

    def test_topics_namespace_does_not_collide_with_section_weights(self):
        # a "table" INTENT's section weights (get_weight) and a "table" TOPIC's weight
        # (get_topic_weight, under the topics: sub-namespace) must not leak into each other.
        p = _write(self.tmp, "table:\n  financial_results: 1.3\ntopics:\n  table:\n    table: 2.0\n")
        self.assertEqual(get_weight("table", "financial_results", path=p), 1.3)
        self.assertEqual(get_topic_weight("table", "table", path=p), 2.0)
        self.assertEqual(get_weight("table", "table", path=p), 1.0)  # no section literally named "table"

    def test_real_config_file_loads_and_parses(self):
        self.assertEqual(get_topic_weight("numeric", "table", path=DEFAULT_PATH), 1.6)
        self.assertEqual(get_topic_weight("table", "table", path=DEFAULT_PATH), 2.0)
        self.assertEqual(get_topic_weight("causal", "table", path=DEFAULT_PATH), 1.0)


if __name__ == "__main__":
    unittest.main()
