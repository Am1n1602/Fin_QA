import unittest

from evaluation.baselines.llm_only import answer
from evaluation.baselines.tests._fakes import FakeProvider


class LlmOnly(unittest.TestCase):
    def test_answer_shape(self):
        p = FakeProvider("TCS revenue was roughly Rs 2.6 lakh crore.")
        out = answer("What was TCS's revenue in FY2026?", p)
        self.assertTrue(out["llm_used"])
        self.assertIn("2.6", out["response"]["answer"])
        # no tools at all -> no evidence, no citations
        self.assertEqual(out["response"]["evidence"], [])
        self.assertEqual(out["response"]["sources"], [])
        self.assertEqual(p.usage["requests_made"], 1)
        self.assertIn("financial analyst", p.calls[0]["system"])


if __name__ == "__main__":
    unittest.main()
