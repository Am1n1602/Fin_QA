import unittest

from evaluation.evaluators.answer import (
    CitationEvaluator,
    CorrectnessEvaluator,
    GroundednessEvaluator,
)


def _result(answer="", claims=None, evidence=None, calculations=None, sources=None, checks=None):
    return {
        "response": {
            "answer": answer, "claims": claims or [],
            "evidence": evidence or [], "calculations": calculations or [],
            "sources": sources or [],
        },
        "verification": {"checks": checks or []},
    }


class Groundedness(unittest.TestCase):
    ev = GroundednessEvaluator()

    def test_all_grounded(self):
        r = self.ev.score({}, _result(
            claims=[{"text": "a", "evidence_ids": ["e1"]}, {"text": "b", "evidence_ids": ["e1", "e2"]}],
            evidence=[{"evidence_id": "e1"}, {"evidence_id": "e2"}]))
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["metrics"]["grounded_rate"], 1.0)

    def test_missing_evidence_id(self):
        r = self.ev.score({}, _result(
            claims=[{"text": "a", "evidence_ids": ["ghost"]}],
            evidence=[{"evidence_id": "e1"}]))
        self.assertEqual(r["verdict"], "fail")

    def test_verifier_citation_missing(self):
        r = self.ev.score({}, _result(
            claims=[{"text": "a", "evidence_ids": ["e1"]}],
            evidence=[{"evidence_id": "e1"}],
            checks=[{"kind": "citation", "verdict": "citation_missing", "text": "a"}]))
        self.assertEqual(r["metrics"]["grounded_claims"], 0)

    def test_na_without_claims(self):
        self.assertEqual(self.ev.score({}, _result())["verdict"], "na")


class Citation(unittest.TestCase):
    ev = CitationEvaluator()

    def test_section_match_recall_precision(self):
        rec = {"reference_sources": [{"section": "risk_factors", "page": 12}]}
        res = _result(sources=[{"section": "risk_factors", "page": 12, "title": "TCS Q4 FY26"}])
        r = self.ev.score(rec, res)
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["metrics"]["recall"], 1.0)
        self.assertEqual(r["metrics"]["precision"], 1.0)

    def test_no_match(self):
        rec = {"reference_sources": [{"section": "risk_factors"}]}
        res = _result(sources=[{"section": "balance_sheet"}])
        r = self.ev.score(rec, res)
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["metrics"]["recall"], 0.0)

    def test_na_without_reference(self):
        self.assertEqual(self.ev.score({}, _result())["verdict"], "na")


class Correctness(unittest.TestCase):
    ev = CorrectnessEvaluator()

    def test_numeric_delegates(self):
        rec = {"answer_type": "numeric", "reference_value": 10.0, "reference_unit": "pct",
               "tolerance_pct": 1.0}
        r = self.ev.score(rec, _result("the figure was 10.0 pct"))
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["metrics"]["mode"], "numeric")

    def test_keyword_coverage(self):
        rec = {"answer_type": "text", "must_contain": ["TCS", "INFY"]}
        self.assertEqual(self.ev.score(rec, _result("TCS beats INFY on margin"))["verdict"], "pass")
        self.assertEqual(self.ev.score(rec, _result("nothing here"))["verdict"], "fail")

    def test_na_without_anything(self):
        self.assertEqual(self.ev.score({"answer_type": "text"}, _result("x"))["verdict"], "na")


if __name__ == "__main__":
    unittest.main()
