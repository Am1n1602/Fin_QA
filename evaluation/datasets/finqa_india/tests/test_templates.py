import unittest

from evaluation.datasets.finqa_india import templates as T
from evaluation.datasets.finqa_india.generate import _pphrase


class Templates(unittest.TestCase):
    def test_phrase_maps_nonempty_and_stringy(self):
        for m in (T.METRICS, T.RATIOS, T.VALUATION, T.GROWTH_METRICS, T.CHANGE_RATIOS, T.DOC_TOPICS):
            self.assertTrue(m)
            self.assertTrue(all(isinstance(k, str) and isinstance(v, str) for k, v in m.items()))

    def test_no_template_starts_with_a_ticker_like_word(self):
        # opening words must not collide with the planner's word-token company matcher
        bad = {"state", "rank"}  # 'rank' is an intent trigger, allowed only in analytical
        for group in (T.FACTUAL_Q, T.NUMERIC_Q, T.GROWTH_Q, T.COMPARE2_Q, T.WHY_Q, T.HOW_Q,
                      T.CROSSVAL_Q, T.SEGMENT_Q, T.OVERVIEW_Q):
            for q in group:
                self.assertNotIn(q.split()[0].lower(), bad, q)

    def test_templates_format_cleanly(self):
        fill = dict(name="TCS", name2="INFY", name3="WIPRO", phrase="return on equity",
                    period="FY2026", direction="rise", mechanism="volumes grew", topic="risk")
        for group in (T.FACTUAL_Q, T.NUMERIC_Q, T.GROWTH_Q, T.COMPARE2_Q, T.COMPARE3_Q,
                      T.WHY_Q, T.HOW_Q, T.CROSSVAL_Q, T.CROSSDOC_Q, T.SEGMENT_Q,
                      T.SEGMENT_DRIVER_Q, T.DECOMPOSE_Q, T.OVERVIEW_Q):
            for q in group:
                self.assertTrue(q.format(**fill).strip())

    def test_direction_word(self):
        self.assertEqual(T.direction_word(5.0), "rise")
        self.assertEqual(T.direction_word(-2.0), "decline")
        self.assertEqual(T.direction_word(None), "change")

    def test_period_phrase(self):
        self.assertEqual(_pphrase("latest_quarter"), "the latest quarter")
        self.assertEqual(_pphrase("FY2026"), "FY2026")


if __name__ == "__main__":
    unittest.main()
