import unittest

from evaluation.evaluators.operations import OperationsEvaluator


class Operations(unittest.TestCase):
    def _rows(self):
        return [
            {"latency_ms": 10.0, "trace": [{"tool": "get_metric", "latency_ms": 2.0}],
             "llm": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
            {"latency_ms": 30.0, "trace": [
                {"tool": "search_documents", "latency_ms": 5.0},
                {"tool": "search_documents", "latency_ms": 7.0}],
             "llm": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
            {"latency_ms": 20.0, "trace": [], "llm": {}},
        ]

    def test_aggregation(self):
        out = OperationsEvaluator().run(self._rows())
        self.assertEqual(out["n_questions"], 3)
        self.assertEqual(out["latency_ms"]["p50"], 20.0)
        self.assertEqual(out["retrieval_latency_ms"]["n_calls"], 2)
        self.assertEqual(out["tool_calls_total"], 3)
        self.assertEqual(out["llm"]["total_tokens"], 120)
        self.assertEqual(out["llm"]["questions_using_llm"], 1)

    def test_cost_zero_by_default(self):
        out = OperationsEvaluator(model="openai/gpt-oss-120b").run(self._rows())
        self.assertEqual(out["llm"]["est_cost_usd_total"], 0.0)

    def test_cost_with_pricing(self):
        out = OperationsEvaluator(model="x", pricing={"x": (1.0, 2.0)}).run(self._rows())
        # 100/1e6*1 + 20/1e6*2 = 0.00014
        self.assertAlmostEqual(out["llm"]["est_cost_usd_total"], 0.00014, places=6)

    def test_empty(self):
        out = OperationsEvaluator().run([])
        self.assertEqual(out["n_questions"], 0)
        self.assertIsNone(out["latency_ms"]["p50"])


if __name__ == "__main__":
    unittest.main()
