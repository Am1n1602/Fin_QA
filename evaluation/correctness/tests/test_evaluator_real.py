"""§23 layered correctness evaluation exercised end-to-end against the real corpus and
the real finqa_v2_eval.jsonl dataset. Deterministic only (`use_llm=False`, and
`use_llm_judge=False` on the evaluator too) -- no LLM tokens spent; Layer 3 is validated
separately in test_evaluator.py with a fake provider.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[3]
_DATASET = _ROOT / "evaluation" / "datasets" / "finqa_v2_eval.jsonl"
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists() and _DATASET.exists(),
                     "finqa_v2.db / finqa_v2_eval.jsonl not built")
class LayeredCorrectnessReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.reasoning import ReasoningOrchestrator
        from finqa_v2.retrieval.evaluate import build_retriever

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        retriever = build_retriever(cls.repos, bm25_path=_BM25, vector_dir=_ROOT / "database" / "data" / "finqa_v2_vec") \
            if _BM25.exists() else None
        cls.orch = ReasoningOrchestrator(cls.repos, retriever=retriever)
        cls.records = [json.loads(l) for l in _DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_numeric_records_pass_layer1_and_layer2(self):
        from evaluation.correctness.evaluator import LayeredCorrectnessEvaluator

        ev = LayeredCorrectnessEvaluator()
        numeric = [r for r in self.records if r.get("answer_type") == "numeric"][:5]
        self.assertTrue(numeric)
        results = []
        for rec in numeric:
            rr = self.orch.answer(rec["question"], use_llm=False)
            report = ev.score(rec, rr.to_dict())
            results.append((rec["id"], report["verdict"], report["detail"]))
        passes = sum(1 for _, v, _ in results if v == "pass")
        self.assertGreater(passes, 0, results)

    def test_layer2_citation_metrics_shape_is_well_formed_even_without_gold(self):
        from evaluation.correctness.evaluator import LayeredCorrectnessEvaluator

        ev = LayeredCorrectnessEvaluator()
        rec = next(r for r in self.records if r.get("answer_type") == "numeric")
        rr = self.orch.answer(rec["question"], use_llm=False)
        report = ev.score(rec, rr.to_dict())
        citation = report["metrics"]["layer2_citation"]
        self.assertIn("precision", citation)
        self.assertIn("claim_to_evidence_accuracy", citation)
        # finqa_v2_eval.jsonl carries no reference_document_ids yet (Phase 16's own
        # finding) -- gold-dependent metrics must be None, not a misleading 0.0.
        self.assertIsNone(citation["precision"])

    def test_a_wrong_answer_fails_layer1(self):
        from evaluation.correctness.evaluator import LayeredCorrectnessEvaluator

        ev = LayeredCorrectnessEvaluator()
        rec = next(r for r in self.records if r.get("answer_type") == "numeric")
        rr = self.orch.answer(rec["question"], use_llm=False)
        result = rr.to_dict()
        # corrupt the answer text so Layer 1's figure extraction can't possibly match
        result["response"] = dict(result["response"], answer="I have no idea what the number is.")
        report = ev.score(rec, result)
        self.assertEqual(report["verdict"], "fail")


if __name__ == "__main__":
    unittest.main()
