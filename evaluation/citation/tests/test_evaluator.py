import unittest

from evaluation.citation.evaluator import GoldCitation, evaluate


def _ev(evidence_id, *, type="document", document_id=None, page=None):
    return {"evidence_id": evidence_id, "type": type, "document_id": document_id, "page": page}


class Evaluate(unittest.TestCase):
    def test_no_claims_returns_none_metrics(self):
        r = evaluate([], {}, [GoldCitation(document_id=1)])
        self.assertIsNone(r["claim_to_evidence_accuracy"])
        self.assertEqual(r["n_claims"], 0)

    def test_no_gold_returns_none_for_gold_dependent_metrics_not_zero(self):
        claims = [{"evidence_ids": ["ev-1"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5)}
        r = evaluate(claims, evidence, [])
        self.assertIsNone(r["precision"])
        self.assertIsNone(r["recall"])
        self.assertIsNone(r["f1"])
        self.assertIsNone(r["document_accuracy"])
        self.assertIsNone(r["page_accuracy"])
        # claim_to_evidence_accuracy doesn't need gold -- it's a pure traceability check
        self.assertEqual(r["claim_to_evidence_accuracy"], 1.0)

    def test_claim_to_evidence_accuracy_penalizes_a_dangling_evidence_id(self):
        claims = [{"evidence_ids": ["ev-1", "ev-MISSING"]}, {"evidence_ids": ["ev-1"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5)}
        r = evaluate(claims, evidence, [])
        self.assertEqual(r["claim_to_evidence_accuracy"], 0.5)   # only the 2nd claim is fully traceable

    def test_claim_with_no_evidence_ids_is_not_traceable(self):
        claims = [{"evidence_ids": []}]
        r = evaluate(claims, {}, [])
        self.assertEqual(r["claim_to_evidence_accuracy"], 0.0)

    def test_perfect_match_scores_1_everywhere(self):
        claims = [{"evidence_ids": ["ev-1"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5, page=3)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5, page=3)])
        self.assertEqual(r["precision"], 1.0)
        self.assertEqual(r["recall"], 1.0)
        self.assertEqual(r["f1"], 1.0)
        self.assertEqual(r["document_accuracy"], 1.0)
        self.assertEqual(r["page_accuracy"], 1.0)

    def test_wrong_document_is_zero_precision_and_recall(self):
        claims = [{"evidence_ids": ["ev-1"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=99)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5)])
        self.assertEqual(r["precision"], 0.0)
        self.assertEqual(r["recall"], 0.0)
        self.assertEqual(r["f1"], 0.0)
        self.assertEqual(r["document_accuracy"], 0.0)

    def test_recall_counts_distinct_gold_documents_found_across_claims(self):
        claims = [{"evidence_ids": ["ev-1"]}, {"evidence_ids": ["ev-2"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5), "ev-2": _ev("ev-2", document_id=6)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5), GoldCitation(document_id=6),
                                        GoldCitation(document_id=7)])
        self.assertAlmostEqual(r["recall"], 2 / 3, places=4)
        self.assertEqual(r["precision"], 1.0)   # both cited docs are gold, just not all gold was found

    def test_page_accuracy_only_counted_when_gold_specifies_a_page(self):
        claims = [{"evidence_ids": ["ev-1"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5, page=9)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5, page=None)])
        self.assertEqual(r["document_accuracy"], 1.0)
        self.assertIsNone(r["page_accuracy"])   # gold has no page to check against

    def test_page_mismatch_is_scored(self):
        claims = [{"evidence_ids": ["ev-1"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5, page=9)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5, page=2)])
        self.assertEqual(r["document_accuracy"], 1.0)
        self.assertEqual(r["page_accuracy"], 0.0)

    def test_non_document_evidence_is_excluded_from_citation_metrics(self):
        # a claim citing only a numeric-fact evidence item has nothing to check citations
        # against -- it doesn't corrupt document_accuracy with a spurious None-vs-doc.
        claims = [{"evidence_ids": ["ev-fact"]}]
        evidence = {"ev-fact": _ev("ev-fact", type="financial_fact", document_id=None)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5)])
        self.assertEqual(r["n_cited_documents"], 0)
        self.assertIsNone(r["document_accuracy"])
        self.assertEqual(r["claim_to_evidence_accuracy"], 1.0)   # still traceable, just not a doc

    def test_duplicate_citations_of_the_same_document_count_once_for_precision(self):
        claims = [{"evidence_ids": ["ev-1"]}, {"evidence_ids": ["ev-2"]}]
        evidence = {"ev-1": _ev("ev-1", document_id=5), "ev-2": _ev("ev-2", document_id=5)}
        r = evaluate(claims, evidence, [GoldCitation(document_id=5)])
        self.assertEqual(r["n_cited_documents"], 1)
        self.assertEqual(r["precision"], 1.0)
        self.assertEqual(r["recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
