import unittest

from evaluation.baselines.tests._fakes import EmptyRetriever, FakeProvider, FakeRetriever
from evaluation.baselines.vector_rag import answer


class VectorRag(unittest.TestCase):
    def test_answer_uses_retrieved_passage(self):
        p = FakeProvider("TCS revenue in FY2026 was 2,670,210,000,000 INR, per the passage above.")
        out = answer("What was TCS's revenue in FY2026?", FakeRetriever(), repos=None, provider=p)
        self.assertTrue(out["llm_used"])
        self.assertEqual(len(out["response"]["evidence"]), 1)
        self.assertIn("Passages:", p.calls[0]["prompt"])
        self.assertIn("[0]", p.calls[0]["prompt"])

    def test_no_hits_short_circuits_without_calling_the_llm(self):
        p = FakeProvider()
        out = answer("obscure question", EmptyRetriever(), repos=None, provider=p)
        self.assertFalse(out["llm_used"])
        self.assertEqual(p.usage["requests_made"], 0)
        self.assertIn("No relevant passages", out["response"]["answer"])


if __name__ == "__main__":
    unittest.main()
