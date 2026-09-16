import types
import unittest

from evaluation.evaluators.retrieval import _ndcg, score_retrieval


class NDCG(unittest.TestCase):
    def test_perfect_ranking(self):
        self.assertAlmostEqual(_ndcg([1, 1, 0, 0], 4), 1.0)

    def test_relevant_last_is_worse(self):
        self.assertLess(_ndcg([0, 0, 1], 3), 1.0)

    def test_no_relevant(self):
        self.assertEqual(_ndcg([0, 0, 0], 3), 0.0)


class _Chunk:
    def __init__(self, cid, section, text):
        self.company_id, self.section, self.text = cid, section, text


class _Hit:
    def __init__(self, chunk, rank):
        self.chunk, self.rank = chunk, rank


class _Retriever:
    modes = ("lexical",)

    def __init__(self, chunks):
        self._chunks = chunks

    def retrieve(self, query, k=10, candidate_k=40, mode="lexical", filters=None, rerank=True):
        return [_Hit(c, i + 1) for i, c in enumerate(self._chunks[:k])]


class _Repos:
    class companies:
        @staticmethod
        def resolve(name):
            return types.SimpleNamespace(company_id=1) if name else None


class ScoreRetrieval(unittest.TestCase):
    def test_hit_at_rank_1(self):
        retr = _Retriever([_Chunk(1, "segment_information", "reportable segment revenue"),
                           _Chunk(1, "notes", "other")])
        cases = [{"id": "c1", "query": "segments", "company": "RELIANCE",
                  "sections": ["segment_information"], "must_contain": ["segment"]}]
        out = score_retrieval(retr, _Repos(), cases, mode="lexical", filter_company=True)
        self.assertEqual(out["recall@1"], 1.0)
        self.assertEqual(out["mrr"], 1.0)
        self.assertEqual(out["ndcg@1"], 1.0)

    def test_miss(self):
        retr = _Retriever([_Chunk(1, "notes", "nothing relevant")])
        cases = [{"id": "c1", "query": "segments", "company": "RELIANCE",
                  "sections": ["segment_information"], "must_contain": ["segment"]}]
        out = score_retrieval(retr, _Repos(), cases, mode="lexical", filter_company=True)
        self.assertEqual(out["recall@5"], 0.0)
        self.assertEqual(out["mrr"], 0.0)

    def test_unavailable_mode(self):
        out = score_retrieval(_Retriever([]), _Repos(), [], mode="vector")
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
