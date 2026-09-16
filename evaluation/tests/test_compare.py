import unittest

from evaluation.regression.compare import compare, extract_metrics


def _report(**agg):
    base = {
        "intent_match": {"checked": 10, "passed": 9},
        "numerical": {"accuracy": 0.9},
        "correctness": {"accuracy": 0.8},
        "groundedness": {"mean_grounded_rate": 0.95},
        "citation": {"mean_f1": 0.6},
        "abstention": {"accuracy": 1.0},
        "unsupported_claims": {"mean_rate": 0.02},
        "operations": {"latency_ms": {"p50": 20.0, "p95": 40.0},
                       "llm": {"tokens_per_question": 3000}},
    }
    base.update(agg)
    return {"aggregates": base,
            "retrieval": {"lexical": {"recall@5": 0.78, "mrr": 0.68, "ndcg@10": 0.7}}}


class Extract(unittest.TestCase):
    def test_flatten(self):
        m = extract_metrics(_report())
        self.assertEqual(m["intent_match_rate"], 0.9)
        self.assertEqual(m["numerical.accuracy"], 0.9)
        self.assertEqual(m["retrieval.lexical.recall@5"], 0.78)


class Compare(unittest.TestCase):
    def test_no_change_is_ok(self):
        d = compare(_report(), _report())
        self.assertTrue(d["ok"])
        self.assertEqual(d["regressions"], [])

    def test_numerical_regression(self):
        d = compare(_report(), _report(numerical={"accuracy": 0.80}))
        self.assertFalse(d["ok"])
        self.assertEqual(d["regressions"][0]["metric"], "numerical.accuracy")

    def test_within_slack_not_flagged(self):
        d = compare(_report(), _report(numerical={"accuracy": 0.89}))
        self.assertTrue(d["ok"])

    def test_latency_relative_slack(self):
        # p50 20 -> 24 is within 25% slack
        self.assertTrue(compare(_report(), _report(
            operations={"latency_ms": {"p50": 24.0, "p95": 40.0},
                        "llm": {"tokens_per_question": 3000}}))["ok"])
        # p50 20 -> 30 exceeds it
        self.assertFalse(compare(_report(), _report(
            operations={"latency_ms": {"p50": 30.0, "p95": 40.0},
                        "llm": {"tokens_per_question": 3000}}))["ok"])

    def test_improvement_detected(self):
        d = compare(_report(), _report(citation={"mean_f1": 0.9}))
        self.assertTrue(d["ok"])
        self.assertTrue(any(r["metric"] == "citation.mean_f1" for r in d["improvements"]))

    def test_lower_better_unsupported(self):
        d = compare(_report(), _report(unsupported_claims={"mean_rate": 0.10}))
        self.assertFalse(d["ok"])


if __name__ == "__main__":
    unittest.main()
