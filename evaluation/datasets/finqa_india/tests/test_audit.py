import unittest

from evaluation.datasets.finqa_india.audit import QUOTAS, TOTAL, audit, scaled_quotas


def _rec(cat, **kw):
    base = {"category": cat, "question": f"q {cat} {kw.get('i', 0)}", "companies": ["TCS"],
            "answer_type": "text", "expected_intent": "numeric_fact",
            "reference_value": None, "should_abstain": False}
    base.update(kw)
    return base


class Audit(unittest.TestCase):
    def test_scaled_quotas_sum_close_to_target(self):
        self.assertEqual(sum(QUOTAS.values()), TOTAL)
        sc = scaled_quotas(500)
        self.assertTrue(480 <= sum(sc.values()) <= 520)
        self.assertEqual(set(sc), set(QUOTAS))

    def test_counts_and_gaps(self):
        recs = ([_rec("factual", i=i, answer_type="numeric", reference_value=1.0) for i in range(5)]
                + [_rec("why", i=i) for i in range(3)])
        a = audit(recs, target=TOTAL)
        self.assertEqual(a["n"], 8)
        self.assertEqual(a["by_category"]["factual"], 5)
        self.assertEqual(a["numeric"], 5)
        self.assertEqual(a["numeric_gold_coverage"], 1.0)
        self.assertIn("factual", a["quota_gaps"])
        self.assertFalse(a["quota_met"])

    def test_dup_detection(self):
        recs = [_rec("factual", question="same"), _rec("factual", question="same")]
        self.assertEqual(audit(recs)["dup_questions"], 1)


if __name__ == "__main__":
    unittest.main()
