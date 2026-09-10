"""ClaimGraphView over real orchestrator output against finqa_v2.db."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_BM25 = Path(__file__).resolve().parents[3] / "database" / "data" / "finqa_v2_bm25.pkl"


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "needs database/data/finqa_v2.db")
class TestClaimGraphReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.reasoning import ReasoningOrchestrator

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("TCS") is None:
            raise unittest.SkipTest("TCS not in db")
        retriever = None
        if _BM25.exists():
            try:
                from finqa_v2.retrieval import BM25Index, HybridRetriever

                retriever = HybridRetriever(cls.repos, bm25=BM25Index.load(_BM25))
            except Exception:
                pass
        cls.orch = ReasoningOrchestrator(cls.repos, retriever=retriever)
        cls.has_retriever = retriever is not None

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_numeric_answer_graph(self):
        r = self.orch.answer("What was TCS ROE in FY2026?")
        cg = r.claim_graph
        self.assertIsNotNone(cg)
        json.dumps(r.to_dict())
        self.assertGreaterEqual(cg["counts"]["claims"], 1)
        self.assertGreaterEqual(cg["counts"]["calculations"], 1)
        # every claim explanation resolves only to evidence that exists in the graph
        node_ids = {n["id"] for n in cg["graph"]["nodes"]}
        for c in cg["claims"]:
            for e in c["evidence"]:
                self.assertIn(e["evidence_id"], node_ids)
        # the ROE calc appears with a re-runnable expression
        self.assertTrue(any(k["expression"] for c in cg["claims"] for k in c["calculations"])
                        or any(n["type"] == "calculation" for n in cg["graph"]["nodes"]))

    def test_causal_answer_graph_has_sources_when_retriever_present(self):
        r = self.orch.answer("Why did HCLTECH profitability decline?")
        cg = r.claim_graph
        self.assertEqual(cg["counts"]["claims"], len(cg["claims"]))
        if self.has_retriever:
            self.assertGreaterEqual(cg["counts"]["sources"], 1)
            self.assertTrue(any(s["page"] is not None for s in cg["sources"]))

    def test_graph_edges_are_well_formed(self):
        r = self.orch.answer("Compare TCS and Infosys on ROE.")
        g = r.claim_graph["graph"]
        ids = {n["id"] for n in g["nodes"]}
        rels = {e["rel"] for e in g["edges"]}
        self.assertTrue(rels.issubset({"supported_by", "computed_by", "computed_from",
                                       "cites", "derived_from"}))
        for e in g["edges"]:
            self.assertIn(e["from"], ids)
            self.assertIn(e["to"], ids)


if __name__ == "__main__":
    unittest.main()
