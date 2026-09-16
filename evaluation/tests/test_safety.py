import unittest

from evaluation.evaluators.safety import (
    AbstentionEvaluator,
    UnsupportedClaimEvaluator,
    did_abstain,
)


def _result(answer="", claims=None, confidence=0.9, abstained=False):
    return {
        "response": {"answer": answer, "claims": claims or [], "confidence": confidence},
        "verification": {"abstained": abstained},
    }


class DidAbstain(unittest.TestCase):
    def test_signal_phrase(self):
        self.assertTrue(did_abstain(_result("That data is not available in the database.")))

    def test_unverified_prefix(self):
        self.assertTrue(did_abstain(_result("[unverified] TCS revenue was 5.")))

    def test_verifier_flag(self):
        self.assertTrue(did_abstain(_result("something", abstained=True)))

    def test_confident_not_supported_is_a_finding_not_an_abstention(self):
        # a deliberate `not_supported` adjudication (cross-validation) is a real answer
        self.assertFalse(did_abstain(_result(
            "The claim is not supported by the financials.",
            claims=[{"status": "not_supported"}], confidence=0.3)))

    def test_confident_answer_is_not_abstention(self):
        self.assertFalse(did_abstain(_result(
            "TCS revenue was 100.", claims=[{"status": "supported"}], confidence=0.9)))


class Abstention(unittest.TestCase):
    ev = AbstentionEvaluator()

    def test_pass_when_should_and_did(self):
        r = self.ev.score({"should_abstain": True},
                          _result("No evidence was found for that period."))
        self.assertEqual(r["verdict"], "pass")

    def test_fail_when_should_but_answered(self):
        r = self.ev.score({"should_abstain": True},
                          _result("TCS FY1998 revenue was 42.", claims=[{"status": "supported"}]))
        self.assertEqual(r["verdict"], "fail")

    def test_warn_on_over_abstention(self):
        r = self.ev.score({"should_abstain": False}, _result("no evidence"))
        self.assertEqual(r["verdict"], "warn")

    def test_pass_when_answerable_and_answered(self):
        r = self.ev.score({"should_abstain": False},
                          _result("TCS revenue was 100.", claims=[{"status": "supported"}]))
        self.assertEqual(r["verdict"], "pass")


class Unsupported(unittest.TestCase):
    ev = UnsupportedClaimEvaluator()

    def test_all_supported(self):
        r = self.ev.score({}, _result("x", claims=[
            {"status": "supported", "evidence_ids": ["e1"]},
            {"status": "partially_supported", "evidence_ids": ["e2"]}]))
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["metrics"]["unsupported_rate"], 0.0)

    def test_uncited_claim_counts(self):
        r = self.ev.score({}, _result("x", claims=[
            {"status": "supported", "evidence_ids": []},
            {"status": "supported", "evidence_ids": ["e2"]}]))
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["metrics"]["n_unsupported"], 1)

    def test_na_for_should_abstain(self):
        r = self.ev.score({"should_abstain": True},
                          _result("x", claims=[{"status": "not_supported", "evidence_ids": ["e"]}]))
        self.assertEqual(r["verdict"], "na")


if __name__ == "__main__":
    unittest.main()
