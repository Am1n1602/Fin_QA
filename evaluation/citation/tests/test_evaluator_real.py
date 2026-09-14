"""§22 citation evaluation exercised end-to-end against the real corpus -- the first time
this repo has ever scored citations against verified, DB-probed gold rather than an empty
`reference_sources` list. Uses real companies confirmed (Phase 16 investigation) to carry
narrative content (mda/earnings_call), unlike finqa_v2_eval.jsonl's causal questions
(TCS/HCLTECH/WIPRO), which target companies with ZERO such content in this corpus -- see
docs/file-guide.md's Phase 16 writeup for that finding.

Deterministic only (`use_llm=False`) -- no LLM tokens spent.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[3]
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"
_VEC = _ROOT / "database" / "data" / "finqa_v2_vec"

# confirmed via direct SQL probe (Phase 16) to have real mda/earnings_call chunks
_NARRATIVE_RICH = ("RELIANCE", "ADANIENT", "SUNPHARMA")


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists() and _BM25.exists(), "finqa_v2.db / BM25 index not built")
class CitationEvaluationReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.reasoning import ReasoningOrchestrator
        from finqa_v2.retrieval.evaluate import build_retriever

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        for tkr in _NARRATIVE_RICH:
            if cls.repos.companies.resolve(tkr) is None:
                cls.repos.close()
                raise unittest.SkipTest(f"{tkr} not in db")
        cls.retriever = build_retriever(cls.repos, bm25_path=_BM25, vector_dir=_VEC)
        cls.orch = ReasoningOrchestrator(cls.repos, retriever=cls.retriever)

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def _gold_for(self, ticker: str, keyword: str):
        from evaluation.citation.evaluator import GoldCitation
        from evaluation.datasets.retrieval_v21.probe import probe

        cid = self.repos.companies.resolve(ticker).company_id
        hits = probe(self.repos.connection, company_id=cid, sections=["mda", "earnings_call"],
                    keyword=keyword, limit=10)
        return [GoldCitation(document_id=h.document_id) for h in hits], hits

    def test_causal_answer_citations_score_against_verified_gold(self):
        from evaluation.citation.evaluator import evaluate

        ticker, metric = "RELIANCE", "revenue"
        gold, hits = self._gold_for(ticker, metric)
        self.assertTrue(gold, f"probe found no real {metric!r} mda/earnings_call chunks for {ticker} "
                              "-- test setup assumption broke, not a citation-scoring result")

        r = self.orch.answer(f"Why did {ticker} {metric} change?", use_llm=False)
        self.assertIn("search_documents", r.tools_run)
        evidence_by_id = {e["evidence_id"]: e for e in r.response["evidence"]}
        report = evaluate(r.response["claims"], evidence_by_id, gold)

        # Shape/range assertions -- this is a REAL exploratory measurement, not a fixed
        # expected score, so we assert validity, not a specific number.
        for key in ("precision", "recall", "f1", "claim_to_evidence_accuracy"):
            self.assertIsNotNone(report[key], report)
            self.assertGreaterEqual(report[key], 0.0)
            self.assertLessEqual(report[key], 1.0)
        self.assertEqual(report["claim_to_evidence_accuracy"], 1.0,
                         "every claim's evidence_ids must resolve inside the same response's own evidence list")

    def test_a_totally_unrelated_gold_set_scores_zero_not_none(self):
        # sanity check the metric behaves correctly when the answer's real citations don't
        # overlap fabricated gold at all -- distinguishes "found nothing relevant" (0.0)
        # from "no gold was given" (None), which test_evaluator.py covers directly.
        from evaluation.citation.evaluator import GoldCitation, evaluate

        r = self.orch.answer("Why did RELIANCE revenue change?", use_llm=False)
        evidence_by_id = {e["evidence_id"]: e for e in r.response["evidence"]}
        fake_gold = [GoldCitation(document_id=-999999)]
        report = evaluate(r.response["claims"], evidence_by_id, fake_gold)
        self.assertEqual(report["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
