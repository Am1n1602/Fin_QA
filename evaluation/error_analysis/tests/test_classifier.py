import unittest

from evaluation.error_analysis.classifier import ChunkMeta, classify


def _gold(**kw) -> ChunkMeta:
    base = dict(chunk_id=1, document_id=100, company_id=10, chunk_index=5,
               section="financial_results", topic="prose", financial_year=2026)
    base.update(kw)
    return ChunkMeta(**base)


def _hit(**kw) -> ChunkMeta:
    base = dict(chunk_id=2, document_id=200, company_id=10, chunk_index=1,
               section="mda", topic="prose", financial_year=2026)
    base.update(kw)
    return ChunkMeta(**base)


class Classify(unittest.TestCase):
    def test_no_company_match_takes_priority(self):
        result = classify(intent="numeric", had_company=True, company_resolved=False,
                          gold=[_gold()], top_hits=[_hit()])
        self.assertEqual(result, "NO_COMPANY_MATCH")

    def test_no_ticker_given_is_not_a_company_match_failure(self):
        result = classify(intent="numeric", had_company=False, company_resolved=True,
                          gold=[_gold()], top_hits=[])
        self.assertNotEqual(result, "NO_COMPANY_MATCH")

    def test_multi_hop_intent_always_flagged(self):
        result = classify(intent="multi_hop", had_company=True, company_resolved=True,
                          gold=[_gold()], top_hits=[_hit(section="financial_results")])
        self.assertEqual(result, "MULTI_HOP_FAILURE")

    def test_table_retrieval_failure(self):
        gold = [_gold(topic="table")]
        hits = [_hit(topic="prose"), _hit(chunk_id=3, topic="segment")]
        result = classify(intent="table", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertEqual(result, "TABLE_RETRIEVAL_FAILURE")

    def test_table_retrieval_ok_when_a_table_hit_is_present(self):
        gold = [_gold(topic="table")]
        hits = [_hit(topic="table")]
        result = classify(intent="table", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertNotEqual(result, "TABLE_RETRIEVAL_FAILURE")

    def test_wrong_section(self):
        gold = [_gold(section="segment_information")]
        hits = [_hit(company_id=10, section="risk_factors")]
        result = classify(intent="segment", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertEqual(result, "WRONG_SECTION")

    def test_wrong_section_not_flagged_for_a_different_company(self):
        gold = [_gold(company_id=10, section="segment_information")]
        hits = [_hit(company_id=99, section="risk_factors")]
        result = classify(intent="segment", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertNotEqual(result, "WRONG_SECTION")

    def test_wrong_period(self):
        gold = [_gold(section="financial_results", financial_year=2026)]
        hits = [_hit(company_id=10, section="financial_results", financial_year=2027)]
        result = classify(intent="numeric", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertEqual(result, "WRONG_PERIOD")

    def test_stale_document(self):
        gold = [_gold(section="mda", financial_year=None)]
        hits = [_hit(company_id=10, section="mda", is_superseded=True)]
        result = classify(intent="narrative", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertEqual(result, "STALE_DOCUMENT")

    def test_chunk_boundary(self):
        gold = [_gold(document_id=100, chunk_index=5, section="mda", financial_year=None)]
        hits = [_hit(document_id=100, chunk_index=6, company_id=10, section="mda")]
        result = classify(intent="narrative", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertEqual(result, "CHUNK_BOUNDARY")

    def test_chunk_boundary_requires_same_document(self):
        gold = [_gold(document_id=100, chunk_index=5, section="mda", financial_year=None)]
        hits = [_hit(document_id=999, chunk_index=6, company_id=10, section="mda")]
        result = classify(intent="narrative", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertNotEqual(result, "CHUNK_BOUNDARY")

    def test_semantic_miss(self):
        # same section, different document/chunk -- isolates the miss to the mode dimension
        gold = [_gold(section="mda", financial_year=None, document_id=100, chunk_index=5)]
        hits = [_hit(company_id=10, section="mda", document_id=777, chunk_index=1)]
        result = classify(intent="causal", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits, lexical_found=True, vector_found=False)
        self.assertEqual(result, "SEMANTIC_MISS")

    def test_lexical_miss(self):
        gold = [_gold(section="mda", financial_year=None, document_id=100, chunk_index=5)]
        hits = [_hit(company_id=10, section="mda", document_id=777, chunk_index=1)]
        result = classify(intent="causal", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits, lexical_found=False, vector_found=True)
        self.assertEqual(result, "LEXICAL_MISS")

    def test_falls_back_to_insufficient_context(self):
        gold = [_gold(section="mda", financial_year=None)]
        hits = [_hit(company_id=10, section="mda", document_id=100, chunk_index=500)]
        result = classify(intent="causal", had_company=True, company_resolved=True,
                          gold=gold, top_hits=hits)
        self.assertEqual(result, "INSUFFICIENT_CONTEXT")

    def test_missing_document_is_never_produced(self):
        # by construction (§6 note in classifier.py): gold always exists in this benchmark
        for _ in range(50):
            result = classify(intent="numeric", had_company=True, company_resolved=True,
                              gold=[_gold()], top_hits=[])
            self.assertNotEqual(result, "MISSING_DOCUMENT")


if __name__ == "__main__":
    unittest.main()
