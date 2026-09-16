"""BM25 + vector + hybrid retrieval on the in-memory fixture."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from finqa_v2.retrieval.embed import HashEmbedder
from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.retrieval.retriever import HybridRetriever
from finqa_v2.retrieval.tests._fixture import seed
from finqa_v2.retrieval.vector import VectorIndex
from finqa_v2.sqlite import SqliteRepositories


class TestBM25(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.idx = BM25Index.build(self.repos)

    def test_search_ranks_topic_chunk_first(self):
        hits = self.idx.search("oil to chemicals retail digital services segment", k=3)
        self.assertTrue(hits)
        top = self.repos.documents.chunks_for  # noqa
        self.assertGreater(hits[0].score, 0)

    def test_filter_by_company_and_section(self):
        hits = self.idx.search("segment revenue", k=10, filters={"company_id": 999})
        self.assertEqual(hits, [])
        cid = self.repos.companies.get_by_ticker("TCS").company_id
        hits = self.idx.search("segment BFSI manufacturing", k=10,
                               filters={"company_id": cid, "section": ["segment_information"]})
        self.assertTrue(hits)
        for h in hits:
            m = next(mm for cc, mm in zip(self.idx.chunk_ids, self.idx.meta) if cc == h.chunk_id)
            self.assertEqual(m["company_id"], cid)
            self.assertEqual(m["section"], "segment_information")

    def test_save_load_roundtrip(self):
        d = Path(tempfile.mkdtemp()) / "bm25.pkl"
        self.idx.save(d)
        again = BM25Index.load(d)
        self.assertEqual(again.search("dividend board meeting sebi", k=3)[0].chunk_id,
                         self.idx.search("dividend board meeting sebi", k=3)[0].chunk_id)


class TestHybrid(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        bm25 = BM25Index.build(self.repos)
        emb = HashEmbedder(dim=128)
        vec = VectorIndex.build(self.repos, emb, use_faiss=False)
        self.r = HybridRetriever(self.repos, bm25=bm25, vector=vec, embedder=emb)

    def test_modes_available(self):
        self.assertEqual(set(self.r.modes), {"lexical", "vector", "hybrid"})

    def test_lexical_mode(self):
        hits = self.r.retrieve("independent auditor report basis for opinion", k=3, mode="lexical")
        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.section, "auditors_report")
        self.assertEqual(hits[0].rank, 1)
        self.assertIn("doc#", hits[0].citation())

    def test_vector_mode_runs(self):
        hits = self.r.retrieve("cash generated from operating activities", k=3, mode="vector")
        self.assertTrue(hits)

    def test_hybrid_fuses(self):
        hits = self.r.retrieve("segment revenue retail digital services", k=3, mode="hybrid")
        self.assertTrue(hits)
        self.assertIn(hits[0].chunk.section, {"segment_information"})
        self.assertIsNotNone(hits[0].scores["rrf"])

    def test_filter_scopes_results(self):
        cid = self.repos.companies.get_by_ticker("TCS").company_id
        hits = self.r.retrieve("segment", k=5, mode="hybrid", filters={"company_id": cid})
        self.assertTrue(hits)
        self.assertTrue(all(h.chunk.company_id == cid for h in hits))

    def test_lexical_only_retriever_downgrades_hybrid(self):
        r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos))
        self.assertEqual(r.modes, ("lexical",))
        hits = r.retrieve("dividend", k=2, mode="hybrid")   # silently -> lexical
        self.assertTrue(hits)

    def test_reranker_reorders(self):
        class RevReranker:
            name = "rev"
            trivial = False

            def score(self, query, passages):
                return [float(i) for i in range(len(passages))]     # last becomes first

        r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos), reranker=RevReranker())
        base = r.retrieve("segment revenue", k=5, mode="lexical", rerank=False)
        reranked = r.retrieve("segment revenue", k=5, mode="lexical", rerank=True)
        self.assertNotEqual([h.chunk.chunk_id for h in base], [h.chunk.chunk_id for h in reranked])

    def test_intent_none_is_unchanged_from_omitting_the_argument(self):
        # every caller that predates §15 never passes `intent` at all -- confirm the new
        # default keeps their behavior byte-for-byte identical.
        with_default = self.r.retrieve("independent auditor report basis for opinion", k=3, mode="lexical")
        explicit_none = self.r.retrieve("independent auditor report basis for opinion", k=3,
                                        mode="lexical", intent=None)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_none])

    def test_intent_reorders_by_configured_section_weight(self):
        # 3 lexical candidates for this query (see the ranking below); patch the weight
        # lookup (not the real YAML -- that's section_weights.py's own test) so this only
        # exercises the retriever's reordering logic in isolation.
        query = "audit report board dividend opinion"
        baseline = self.r.retrieve(query, k=3, mode="lexical", rerank=False)
        self.assertEqual([h.chunk.section for h in baseline], ["auditors_report", "cover_letter", "notes"])

        def _fake_weight(intent, section):
            return 0.01 if section == "auditors_report" else 1.0

        with mock.patch("finqa_v2.retrieval.retriever._section_weight", side_effect=_fake_weight):
            weighted = self.r.retrieve(query, k=3, mode="lexical", rerank=False, intent="suppress_audit")
        self.assertNotEqual(weighted[0].chunk.section, "auditors_report")
        self.assertIsNotNone(weighted[0].scores["section_weight"])

    def test_intent_demotes_boilerplate_cover_letter_using_the_real_shipped_config(self):
        # this is the exact Phase-2 finding (cover_letter boilerplate outranking real
        # content) reproduced in miniature, and the real section_weights.yaml's `global`
        # cover_letter suppression fixing it -- no mocking, the actual shipped config.
        query = "audit report board dividend opinion"
        baseline = self.r.retrieve(query, k=3, mode="lexical", rerank=False)
        self.assertEqual(baseline[1].chunk.section, "cover_letter")  # ranks #2 unweighted

        weighted = self.r.retrieve(query, k=3, mode="lexical", rerank=False, intent="causal")
        cover_letter_rank = next(h.rank for h in weighted if h.chunk.section == "cover_letter")
        self.assertEqual(cover_letter_rank, 3)  # demoted to last by the global 0.3x weight

    def test_topic_weight_is_multiplied_into_the_combined_weight(self):
        query = "audit report board dividend opinion"
        with mock.patch("finqa_v2.retrieval.retriever._section_weight", return_value=1.0), \
             mock.patch("finqa_v2.retrieval.retriever._topic_weight", return_value=0.01) as fake_topic:
            hits = self.r.retrieve(query, k=3, mode="lexical", rerank=False, intent="whatever")
        fake_topic.assert_called()
        # with every candidate's topic weight forced to the same 0.01, the combined weight
        # collapses to a constant factor -- relative order among candidates is unaffected,
        # but this confirms _topic_weight is actually consulted and folded into the score.
        self.assertTrue(all(h.scores["section_weight"] == 0.01 for h in hits))

    def test_lexical_query_none_is_unchanged_from_omitting_the_argument(self):
        with_default = self.r.retrieve("segment revenue", k=3, mode="lexical")
        explicit_none = self.r.retrieve("segment revenue", k=3, mode="lexical", lexical_query=None)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_none])

    def test_lexical_query_is_used_for_the_bm25_leg_only(self):
        # "dividend" alone doesn't match the segment_information chunks at all; a query
        # that finds nothing verbatim should still find the cover_letter chunk once the
        # BM25 leg is redirected to a lexical_query that actually contains "dividend".
        no_hits = self.r.retrieve("xyzxyz_no_real_word", k=3, mode="lexical", rerank=False)
        self.assertEqual(no_hits, [])
        redirected = self.r.retrieve("xyzxyz_no_real_word", k=3, mode="lexical", rerank=False,
                                     lexical_query="board dividend")
        self.assertTrue(redirected)
        self.assertEqual(redirected[0].chunk.section, "cover_letter")

    def test_intent_weighting_leaves_scores_empty_when_not_used(self):
        hits = self.r.retrieve("segment revenue", k=3, mode="lexical")
        self.assertTrue(all(h.scores["section_weight"] is None for h in hits))

    def test_weighted_fusion_false_is_unchanged_from_omitting_the_argument(self):
        query = "segment revenue retail digital services"
        with_default = self.r.retrieve(query, k=3, mode="hybrid", rerank=False)
        explicit_false = self.r.retrieve(query, k=3, mode="hybrid", rerank=False, weighted_fusion=False)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_false])

    def test_weighted_fusion_with_unconfigured_intent_matches_plain_rrf(self):
        # the shipped fusion_weights.yaml has no benchmark-earned overrides yet -- (1.0, 1.0)
        # for every intent -- so turning the flag on must not change results until it does.
        # intent=None here so §15's separate section/topic reordering (which DOES read the
        # "segment" intent's config) can't confound this fusion-only comparison.
        query = "segment revenue retail digital services"
        plain = self.r.retrieve(query, k=5, mode="hybrid", rerank=False)
        weighted = self.r.retrieve(query, k=5, mode="hybrid", rerank=False, weighted_fusion=True)
        self.assertEqual([h.chunk.chunk_id for h in plain], [h.chunk.chunk_id for h in weighted])

    def test_weighted_fusion_applies_configured_leg_weights(self):
        query = "segment revenue retail digital services"
        with mock.patch("finqa_v2.retrieval.retriever._fusion_weights", return_value=(0.0, 1.0)):
            vector_only = self.r.retrieve(query, k=5, mode="hybrid", rerank=False, weighted_fusion=True)
        direct_vector = self.r.retrieve(query, k=5, mode="vector", rerank=False)
        self.assertEqual([h.chunk.chunk_id for h in vector_only], [h.chunk.chunk_id for h in direct_vector])

    def test_adaptive_pool_false_is_unchanged_from_omitting_the_argument(self):
        query = "segment revenue retail digital services"
        with_default = self.r.retrieve(query, k=3, mode="hybrid", rerank=False, intent="numeric")
        explicit_false = self.r.retrieve(query, k=3, mode="hybrid", rerank=False, intent="numeric",
                                         adaptive_pool=False)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_false])

    def test_adaptive_pool_ignored_without_intent(self):
        query = "segment revenue retail digital services"
        without = self.r.retrieve(query, k=3, mode="hybrid", rerank=False, candidate_k=5)
        with_flag = self.r.retrieve(query, k=3, mode="hybrid", rerank=False, candidate_k=5,
                                    adaptive_pool=True)
        self.assertEqual([h.chunk.chunk_id for h in without], [h.chunk.chunk_id for h in with_flag])

    def test_adaptive_pool_overrides_candidate_k_for_a_configured_intent(self):
        from unittest import mock as _mock

        seen = {}
        real_search = self.r._bm25.search

        def _recording_search(query, k, **kw):
            seen["k"] = k
            return real_search(query, k, **kw)

        with _mock.patch.object(self.r._bm25, "search", side_effect=_recording_search):
            self.r.retrieve("segment revenue", k=3, mode="lexical", rerank=False,
                            candidate_k=5, intent="numeric", adaptive_pool=True)
        self.assertEqual(seen["k"], 25)   # candidate_pool.yaml's real "numeric" value

    def test_adaptive_pool_falls_back_to_callers_candidate_k_for_unconfigured_intent(self):
        from unittest import mock as _mock

        seen = {}
        real_search = self.r._bm25.search

        def _recording_search(query, k, **kw):
            seen["k"] = k
            return real_search(query, k, **kw)

        with _mock.patch("finqa_v2.retrieval.retriever._candidate_k", return_value=17) as fake:
            with _mock.patch.object(self.r._bm25, "search", side_effect=_recording_search):
                self.r.retrieve("segment revenue", k=3, mode="lexical", rerank=False,
                                candidate_k=5, intent="whatever_unconfigured", adaptive_pool=True)
        fake.assert_called_once_with("whatever_unconfigured", default=5)
        self.assertEqual(seen["k"], 17)

    def test_mmr_false_is_unchanged_from_omitting_the_argument(self):
        query = "segment revenue retail digital services"
        with_default = self.r.retrieve(query, k=3, mode="hybrid", rerank=False)
        explicit_false = self.r.retrieve(query, k=3, mode="hybrid", rerank=False, mmr=False)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_false])

    def test_mmr_ignored_outside_hybrid_mode(self):
        query = "independent auditor report basis for opinion"
        without = self.r.retrieve(query, k=3, mode="lexical", rerank=False)
        with_flag = self.r.retrieve(query, k=3, mode="lexical", rerank=False, mmr=True)
        self.assertEqual([h.chunk.chunk_id for h in without], [h.chunk.chunk_id for h in with_flag])

    def test_mmr_ignored_when_no_vector_index(self):
        from finqa_v2.retrieval.lexical import BM25Index

        r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos))   # no vector wired
        query = "independent auditor report basis for opinion"
        without = r.retrieve(query, k=3, mode="hybrid", rerank=False)   # downgrades to lexical
        with_flag = r.retrieve(query, k=3, mode="hybrid", rerank=False, mmr=True)
        self.assertEqual([h.chunk.chunk_id for h in without], [h.chunk.chunk_id for h in with_flag])

    def test_mmr_result_never_exceeds_k(self):
        query = "segment revenue retail digital services"
        hits = self.r.retrieve(query, k=2, mode="hybrid", rerank=False, mmr=True)
        self.assertLessEqual(len(hits), 2)

    def test_mmr_promotes_a_distinct_candidate_over_a_redundant_one(self):
        # force two candidates to identical vectors (perfectly redundant) and a third to an
        # orthogonal one -- low lambda should demote the redundant runner-up in favor of the
        # distinct candidate, even though it doesn't mock relevance itself (real RRF scores).
        query = "segment revenue retail digital services"
        base = self.r.retrieve(query, k=3, mode="hybrid", rerank=False)
        self.assertGreaterEqual(len(base), 3, "fixture needs >=3 hybrid hits for this test")
        ids = [h.chunk.chunk_id for h in base]

        import numpy as np

        def _fake_get_vectors(chunk_ids):
            # every candidate gets a consistent 2D vector (all same dtype/shape, so MMR's
            # dot products never hit a dimension mismatch): top-2 collapsed onto the same
            # vector (perfectly redundant), everything else orthogonal to them.
            out = {}
            for cid in chunk_ids:
                if cid in (ids[0], ids[1]):
                    out[cid] = np.array([1.0, 0.0])
                else:
                    out[cid] = np.array([0.0, 1.0])
            return out

        with mock.patch.object(self.r._vector, "get_vectors", side_effect=_fake_get_vectors):
            diverse = self.r.retrieve(query, k=2, mode="hybrid", rerank=False, mmr=True, mmr_lambda=0.2)
        diverse_ids = [h.chunk.chunk_id for h in diverse]
        self.assertIn(ids[0], diverse_ids)     # top relevance always kept
        self.assertIn(ids[2], diverse_ids)     # distinct candidate promoted over the redundant #2
        self.assertNotIn(ids[1], diverse_ids)

    def test_weighted_fusion_ignored_outside_hybrid_mode(self):
        query = "independent auditor report basis for opinion"
        without = self.r.retrieve(query, k=3, mode="lexical", rerank=False)
        with mock.patch("finqa_v2.retrieval.retriever._fusion_weights", return_value=(5.0, 0.1)):
            with_flag = self.r.retrieve(query, k=3, mode="lexical", rerank=False, weighted_fusion=True)
        self.assertEqual([h.chunk.chunk_id for h in without], [h.chunk.chunk_id for h in with_flag])

    def test_weighted_recency_false_is_unchanged_from_omitting_the_argument(self):
        query = "segment revenue retail digital services"
        with_default = self.r.retrieve(query, k=3, mode="lexical", rerank=False, intent="numeric")
        explicit_false = self.r.retrieve(query, k=3, mode="lexical", rerank=False, intent="numeric",
                                         weighted_recency=False)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_false])

    def test_weighted_recency_ignored_without_intent(self):
        query = "segment revenue retail digital services"
        without_intent = self.r.retrieve(query, k=3, mode="lexical", rerank=False, weighted_recency=True)
        self.assertTrue(all(h.scores["section_weight"] is None for h in without_intent))


class TestWeightedRecency(unittest.TestCase):
    """§20 follow-up: a soft per-candidate recency boost, deliberately distinct from the
    hard latest-year-only filter tried first and REJECTED (see recency_weights.yaml).
    Uses its own tiny corpus (2 chunks, identical text/section/topic, differing only in
    financial_year) rather than the shared fixture, so financial_year is the ONLY thing
    that can explain a ranking change."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        from finqa_v2.models import Company, DocumentChunk, DocumentMeta

        cid = self.repos.companies.upsert(Company(name="Testco", ticker="TEST")).company_id
        old_doc = self.repos.documents.upsert(
            DocumentMeta(company_id=cid, document_type="results_pdf", title="Old", financial_year=2024)
        ).document_id
        new_doc = self.repos.documents.upsert(
            DocumentMeta(company_id=cid, document_type="results_pdf", title="New", financial_year=2026)
        ).document_id
        text = "Revenue from operations grew steadily during the reporting period."
        self.repos.documents.add_chunks([
            DocumentChunk(document_id=old_doc, company_id=cid, chunk_index=0, text=text,
                          section="financial_results", financial_year=2024, topic="prose"),
            DocumentChunk(document_id=new_doc, company_id=cid, chunk_index=0, text=text,
                          section="financial_results", financial_year=2026, topic="prose"),
            # filler chunks unrelated to the query text -- BM25's IDF goes to zero/negative
            # when a term appears in nearly every document of a TINY corpus (N=2, df=2 here
            # would score every candidate identically at 0), so these exist purely to give
            # the corpus enough size for "revenue from operations" to score as distinctive.
            DocumentChunk(document_id=old_doc, company_id=cid, chunk_index=1,
                          text="Segment information for the reporting period by geography.",
                          section="segment_information", financial_year=2024, topic="segment"),
            DocumentChunk(document_id=new_doc, company_id=cid, chunk_index=1,
                          text="Risk factors relating to foreign exchange volatility.",
                          section="risk_factors", financial_year=2026, topic="prose"),
            DocumentChunk(document_id=new_doc, company_id=cid, chunk_index=2,
                          text="Corporate governance report and board composition details.",
                          section="corporate_governance", financial_year=2026, topic="prose"),
        ])
        self.repos.commit()
        self.bm25 = BM25Index.build(self.repos)
        self.r = HybridRetriever(self.repos, bm25=self.bm25)

    def test_both_tied_candidates_are_found_before_recency_weighting_is_applied(self):
        # two chunks with byte-identical text score identically on BM25 -- confirms the
        # fixture is a genuine tie (both present, order unasserted) before recency
        # weighting gets a chance to break it.
        hits = self.r.retrieve("revenue from operations", k=2, mode="lexical", rerank=False)
        self.assertEqual({h.chunk.financial_year for h in hits}, {2024, 2026})

    def test_weighted_recency_promotes_the_more_recent_of_two_tied_candidates(self):
        with mock.patch("finqa_v2.retrieval.retriever._recency_decay", return_value=0.5):
            hits = self.r.retrieve("revenue from operations", k=2, mode="lexical", rerank=False,
                                   intent="numeric", weighted_recency=True)
        self.assertEqual(hits[0].chunk.financial_year, 2026)
        self.assertEqual(hits[1].chunk.financial_year, 2024)

    def test_weighted_recency_decay_of_one_is_a_no_op(self):
        # decay=1.0 (the shipped default for an unconfigured intent) means
        # `1.0 ** anything == 1.0` -- ties stay ties, order falls back to whatever the
        # unweighted pool already had.
        without = self.r.retrieve("revenue from operations", k=2, mode="lexical", rerank=False)
        with_flag = self.r.retrieve("revenue from operations", k=2, mode="lexical", rerank=False,
                                    intent="unconfigured_intent", weighted_recency=True)
        self.assertEqual([h.chunk.chunk_id for h in without], [h.chunk.chunk_id for h in with_flag])


if __name__ == "__main__":
    unittest.main()
