import unittest

from evaluation.evaluators.numerical import NumericalEvaluator, extract_figures, unit_family


class ExtractFigures(unittest.TestCase):
    def test_inr_raw_and_scaled(self):
        self.assertIn(2670210000000.0,
                      extract_figures("TCS revenue in FY2026 was 2,670,210,000,000.00 INR.", "inr"))
        self.assertIn(2.67e12,
                      extract_figures("Revenue was 2.67 lakh crore this year.", "inr"))
        self.assertIn(9.5e9, extract_figures("PAT of Rs 950 crore", "inr"))

    def test_pct(self):
        figs = extract_figures("INFY roe in FY2026 was 31.59 pct. Margin fell 2 percentage points.", "pct")
        self.assertIn(31.59, figs)
        self.assertIn(2.0, figs)

    def test_x_family(self):
        self.assertEqual(extract_figures("D/E stood at 0.34x at year end", "x"), [0.34])

    def test_hyphenated_range_is_not_negative(self):
        self.assertEqual(extract_figures("expected between 10-12%.", "pct"), [12.0])
        self.assertEqual(extract_figures("fell -3.5% last year", "pct"), [-3.5])

    def test_scaled_inr_not_double_counted(self):
        self.assertEqual(extract_figures("PAT was Rs 1,500 crore", "inr"), [1.5e10])

    def test_figures_in_text_order(self):
        self.assertEqual(extract_figures("25.0% in FY2026 vs 31.6% in FY2025", "pct"), [25.0, 31.6])

    def test_family_map(self):
        self.assertEqual(unit_family("%"), "pct")
        self.assertEqual(unit_family("x"), "x")
        self.assertEqual(unit_family("INR"), "inr")


class Numerical(unittest.TestCase):
    def setUp(self):
        self.ev = NumericalEvaluator()

    def _rec(self, **kw):
        base = {"answer_type": "numeric", "reference_value": 31.59,
                "reference_unit": "pct", "tolerance_pct": 1.0}
        base.update(kw)
        return base

    def test_pass_within_tolerance(self):
        r = self.ev.score(self._rec(), {"response": {"answer": "ROE was 31.6 pct."}})
        self.assertEqual(r["verdict"], "pass")
        self.assertTrue(r["metrics"]["within_tolerance"])

    def test_fail_out_of_tolerance(self):
        r = self.ev.score(self._rec(), {"response": {"answer": "ROE was 25.0 pct."}})
        self.assertEqual(r["verdict"], "fail")

    def test_fail_when_only_a_secondary_figure_matches(self):
        r = self.ev.score(self._rec(), {"response": {"answer": "ROE was 25.0% in FY2026, versus 31.6% in FY2025."}})
        self.assertEqual(r["verdict"], "fail")

    def test_headline_sentence_wins_over_component_figures(self):
        rec = self._rec(reference_value=98301700000.0, reference_unit="INR",
                        gold_spec={"name": "ebit"})
        ans = ("X pbt before exceptional in FY2027 Q1 was 46,257,200,000.00 INR. "
               "X ebit in FY2027 Q1 was 98,301,700,000.00 INR.")
        self.assertEqual(self.ev.score(rec, {"response": {"answer": ans}})["verdict"], "pass")

    def test_fail_when_no_figure(self):
        r = self.ev.score(self._rec(), {"response": {"answer": "It improved a lot."}})
        self.assertEqual(r["verdict"], "fail")
        self.assertIsNone(r["metrics"]["closest_abs_error"])

    def test_na_when_no_reference(self):
        r = self.ev.score(self._rec(reference_value=None), {"response": {"answer": "x"}})
        self.assertEqual(r["verdict"], "na")

    def test_inr_magnitude_match(self):
        rec = self._rec(reference_value=2670210000000.0, reference_unit="INR", tolerance_pct=1.0)
        r = self.ev.score(rec, {"response": {"answer": "TCS revenue was 2,670,210,000,000.00 INR."}})
        self.assertEqual(r["verdict"], "pass")
        self.assertTrue(r["metrics"]["exact_match"])


if __name__ == "__main__":
    unittest.main()
