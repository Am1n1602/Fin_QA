import unittest

from finqa_v2.planner.decompose import decompose
from finqa_v2.planner.models import Intent, QueryPlan


def _plan(**kw) -> QueryPlan:
    base = dict(question="", intent=Intent.UNKNOWN, companies=[], metrics=[])
    base.update(kw)
    return QueryPlan(**base)


class Decompose(unittest.TestCase):
    def test_simple_factual_query_is_not_decomposed(self):
        plan = _plan(question="What was TCS's revenue in FY2026?",
                     intent=Intent.NUMERIC_FACT, companies=["TCS"], metrics=["revenue"])
        self.assertEqual(decompose(plan), [])

    def test_comparison_with_two_companies_decomposes_per_company(self):
        plan = _plan(question="Compare TCS and Infosys on ROE.", intent=Intent.COMPARISON,
                     companies=["TCS", "INFY"], metrics=["roe"])
        self.assertEqual(decompose(plan), ["TCS roe", "INFY roe"])

    def test_comparison_with_only_one_company_is_not_decomposed(self):
        plan = _plan(question="How does TCS compare to its peers?", intent=Intent.COMPARISON,
                     companies=["TCS"], metrics=["roe"])
        self.assertEqual(decompose(plan), [])

    def test_causal_without_comparison_language_is_not_decomposed(self):
        plan = _plan(question="Why did TCS margins decline?", intent=Intent.CAUSAL,
                     companies=["TCS"], metrics=["net_profit_margin"])
        self.assertEqual(decompose(plan), [])

    def test_causal_with_two_companies_but_no_comparative_language_is_not_decomposed(self):
        plan = _plan(question="Why did TCS and Infosys margins decline?", intent=Intent.CAUSAL,
                     companies=["TCS", "INFY"], metrics=["net_profit_margin"])
        self.assertEqual(decompose(plan), [])

    def test_complex_causal_comparison_decomposes(self):
        plan = _plan(
            question="Why did TCS margins decline and how did that affect ROE compared with Infosys?",
            intent=Intent.CAUSAL, companies=["TCS", "INFY"], metrics=["roe"],
        )
        subs = decompose(plan)
        self.assertEqual(subs, ["why did TCS roe change", "TCS roe", "INFY roe"])

    def test_no_metric_falls_back_to_performance(self):
        plan = _plan(question="Compare TCS and Infosys.", intent=Intent.COMPARISON,
                     companies=["TCS", "INFY"], metrics=[])
        self.assertEqual(decompose(plan), ["TCS performance", "INFY performance"])

    def test_ranking_is_not_decomposed(self):
        plan = _plan(question="Rank TCS, Infosys and Wipro by ROE.", intent=Intent.RANKING,
                     companies=["TCS", "INFY", "WIPRO"], metrics=["roe"])
        self.assertEqual(decompose(plan), [])


if __name__ == "__main__":
    unittest.main()
