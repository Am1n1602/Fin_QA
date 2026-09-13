import random
import unittest
from dataclasses import dataclass

from evaluation.datasets.retrieval_v21 import categories as C

_ALL_GENERATORS_NEEDING_ONLY_COMPANIES = (
    C.gen_numeric, C.gen_ratio, C.gen_trend, C.gen_narrative, C.gen_causal,
    C.gen_management_commentary, C.gen_table, C.gen_comparison, C.gen_cross_document,
    C.gen_adversarial, C.gen_no_evidence,
)


@dataclass
class _FakeCompany:
    company_id: int
    ticker: str
    name: str = ""


@dataclass
class _FakeSegment:
    name: str
    slug: str = ""


def _companies(n: int = 6) -> list[_FakeCompany]:
    return [_FakeCompany(i, f"CO{i}") for i in range(1, n + 1)]


class Disp(unittest.TestCase):
    def test_known_overrides(self):
        self.assertEqual(C.disp("M&M"), "Mahindra & Mahindra")
        self.assertEqual(C.disp("BAJAJ-AUTO"), "Bajaj Auto")

    def test_unmapped_ticker_passthrough(self):
        self.assertEqual(C.disp("TCS"), "TCS")


class Generators(unittest.TestCase):
    def setUp(self):
        self.companies = _companies()
        self.rng = random.Random(3)

    def test_every_simple_generator_yields_candidates(self):
        for gen_fn in _ALL_GENERATORS_NEEDING_ONLY_COMPANIES:
            cands = list(gen_fn(self.companies, random.Random(3)))
            self.assertTrue(cands, gen_fn.__name__)
            for cand in cands[:5]:
                self.assertTrue(cand.question.strip())
                self.assertTrue(cand.probes)
                self.assertIn(cand.difficulty, {"easy", "medium", "hard"})

    def test_adversarial_and_no_evidence_expect_no_hits(self):
        for gen_fn in (C.gen_adversarial, C.gen_no_evidence):
            for cand in gen_fn(self.companies, random.Random(3)):
                self.assertFalse(cand.expect_hits)
                self.assertIsNotNone(cand.adversarial_type)

    def test_non_adversarial_expect_hits(self):
        for gen_fn in (C.gen_numeric, C.gen_ratio, C.gen_trend, C.gen_narrative,
                       C.gen_causal, C.gen_table):
            for cand in gen_fn(self.companies, random.Random(3)):
                self.assertTrue(cand.expect_hits)

    def test_comparison_uses_two_distinct_companies(self):
        for cand in C.gen_comparison(self.companies, random.Random(3)):
            self.assertEqual(len(cand.company_tickers), 2)
            self.assertNotEqual(cand.company_tickers[0], cand.company_tickers[1])
            self.assertEqual(len(cand.probes), 2)

    def test_segment_generator_needs_segments_map(self):
        segments_by_company = {1: [_FakeSegment("Retail"), _FakeSegment("Wholesale")], 2: []}
        cands = list(C.gen_segment(self.companies, segments_by_company, random.Random(3)))
        tickers_with_hits = {cand.company_tickers[0] for cand in cands}
        self.assertIn("CO1", tickers_with_hits)
        self.assertNotIn("CO2", tickers_with_hits)

    def test_multi_hop_skips_companies_without_segments(self):
        segments_by_company = {1: [_FakeSegment("Retail")], 2: []}
        cands = list(C.gen_multi_hop(self.companies, segments_by_company, random.Random(3)))
        tickers_with_hits = {cand.company_tickers[0] for cand in cands}
        self.assertIn("CO1", tickers_with_hits)
        self.assertNotIn("CO2", tickers_with_hits)

    def test_causal_candidates_have_one_probe_per_phrase(self):
        cands = list(C.gen_causal(self.companies, random.Random(3)))
        self.assertTrue(cands)
        self.assertEqual(len(cands[0].probes), len(C.CAUSAL_PHRASES))


if __name__ == "__main__":
    unittest.main()
