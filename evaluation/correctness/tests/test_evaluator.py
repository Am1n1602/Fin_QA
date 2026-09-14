import json
import unittest

from evaluation.correctness.evaluator import (
    LayeredCorrectnessEvaluator,
    build_judge_prompt,
    gold_evidence_text,
    parse_judge_response,
    run_llm_judge,
)


class _FakeProvider:
    def __init__(self, response_text: str | None = None, raises: bool = False):
        self._text = response_text
        self._raises = raises
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, json_object=False, temperature=0.1, max_tokens=1024):
        self.calls.append({"prompt": prompt, "system": system})
        if self._raises:
            raise RuntimeError("provider unavailable")
        return self._text


def _numeric_record(**over):
    # NumericalEvaluator's bare-number fallback only accepts figures >= 1000 (below that
    # it assumes a bare number in the answer text isn't really a financial figure) -- use
    # a realistic large value so Layer 1 can actually parse the answer text.
    r = {"question": "What was TCS revenue?", "answer_type": "numeric",
        "reference_value": 267021.0, "tolerance_pct": 1.0, "must_contain": []}
    r.update(over)
    return r


def _result(answer="TCS revenue was 267021.0.", claims=None, evidence=None, value=267021.0, **over):
    resp = {"answer": answer, "claims": claims or [], "evidence": evidence or [],
           "calculations": [{"calculation_id": "calc-1", "result": value}] if value is not None else []}
    resp.update(over)
    return {"response": resp}


class GoldEvidenceText(unittest.TestCase):
    def test_no_gold_returns_explicit_marker(self):
        self.assertIn("no gold evidence", gold_evidence_text({}))

    def test_reference_value_included(self):
        txt = gold_evidence_text({"reference_value": 42.0, "reference_unit": "INR"})
        self.assertIn("42.0", txt)
        self.assertIn("INR", txt)

    def test_must_contain_included(self):
        txt = gold_evidence_text({"must_contain": ["margin", "TCS"]})
        self.assertIn("margin", txt)
        self.assertIn("TCS", txt)

    def test_reference_sources_included(self):
        txt = gold_evidence_text({"reference_sources": [{"section": "mda", "document": None, "page": None}]})
        self.assertIn("section=mda", txt)


class JudgePromptAndParsing(unittest.TestCase):
    def test_prompt_contains_all_four_required_inputs(self):
        p = build_judge_prompt("Why did X change?", "Reference value: 42", "X changed because Y.",
                               [{"text": "Y caused X"}])
        self.assertIn("Why did X change?", p)
        self.assertIn("Reference value: 42", p)
        self.assertIn("X changed because Y.", p)
        self.assertIn("Y caused X", p)

    def test_prompt_with_no_claims_says_so_explicitly(self):
        p = build_judge_prompt("Q", "gold", "answer", [])
        self.assertIn("(no claims)", p)

    def test_parse_good(self):
        raw = json.dumps({"correct": True, "confidence": 0.9, "reasoning": "matches gold"})
        d = parse_judge_response(raw)
        self.assertTrue(d["correct"])
        self.assertEqual(d["confidence"], 0.9)

    def test_parse_missing_correct_key_is_none(self):
        self.assertIsNone(parse_judge_response(json.dumps({"confidence": 0.9})))

    def test_parse_no_json_is_none(self):
        self.assertIsNone(parse_judge_response("not json at all"))

    def test_parse_prose_wrapped_json(self):
        raw = 'Here is my verdict:\n{"correct": false, "reasoning": "no support"}\nDone.'
        d = parse_judge_response(raw)
        self.assertFalse(d["correct"])


_JUDGE_SYSTEM_MARKER = "strict correctness judge"


class RunLlmJudge(unittest.TestCase):
    def test_returns_none_when_provider_raises(self):
        provider = _FakeProvider(raises=True)
        d = run_llm_judge("Q", {}, _result(), provider)
        self.assertIsNone(d)

    def test_returns_none_on_malformed_response(self):
        provider = _FakeProvider(response_text="garbage")
        d = run_llm_judge("Q", {}, _result(), provider)
        self.assertIsNone(d)

    def test_returns_parsed_verdict_and_passes_evidence_context(self):
        provider = _FakeProvider(response_text=json.dumps({"correct": True, "confidence": 0.8, "reasoning": "ok"}))
        record = {"must_contain": ["revenue"]}
        d = run_llm_judge("What was TCS revenue?", record, _result(), provider)
        self.assertTrue(d["correct"])
        self.assertIn("revenue", provider.calls[0]["prompt"])   # gold evidence made it into the prompt
        self.assertIn(_JUDGE_SYSTEM_MARKER, provider.calls[0]["system"])


class LayeredCorrectnessEvaluatorTests(unittest.TestCase):
    def test_pass_when_layer1_and_layer2_pass_and_llm_judge_disabled(self):
        ev = LayeredCorrectnessEvaluator()
        record = _numeric_record()
        result = _result(claims=[{"text": "TCS revenue was 100.0.", "evidence_ids": ["ev-1"]}],
                         evidence=[{"evidence_id": "ev-1", "type": "financial_fact"}])
        r = ev.score(record, result)
        self.assertEqual(r["verdict"], "pass")
        self.assertIsNone(r["metrics"]["layer3_llm_judge"])

    def test_fail_when_layer1_rule_based_fails(self):
        ev = LayeredCorrectnessEvaluator()
        record = _numeric_record(reference_value=999.0, tolerance_pct=1.0)
        result = _result(value=100.0)
        r = ev.score(record, result)
        self.assertEqual(r["verdict"], "fail")

    def test_fail_when_claims_are_not_grounded(self):
        ev = LayeredCorrectnessEvaluator()
        record = _numeric_record()
        # claim cites an evidence_id that doesn't exist in the response's own evidence list
        result = _result(claims=[{"text": "TCS revenue was 100.0.", "evidence_ids": ["ev-GHOST"]}],
                         evidence=[])
        r = ev.score(record, result)
        self.assertEqual(r["verdict"], "fail")

    def test_llm_judge_disagreement_downgrades_pass_to_warn_not_fail(self):
        provider = _FakeProvider(response_text=json.dumps({"correct": False, "reasoning": "disputes it"}))
        ev = LayeredCorrectnessEvaluator(use_llm_judge=True, provider=provider)
        record = _numeric_record()
        result = _result(claims=[{"text": "TCS revenue was 100.0.", "evidence_ids": ["ev-1"]}],
                         evidence=[{"evidence_id": "ev-1", "type": "financial_fact"}])
        r = ev.score(record, result)
        self.assertEqual(r["verdict"], "warn")
        self.assertFalse(r["metrics"]["layer3_llm_judge"]["correct"])

    def test_llm_judge_agreement_keeps_pass(self):
        provider = _FakeProvider(response_text=json.dumps({"correct": True, "reasoning": "matches"}))
        ev = LayeredCorrectnessEvaluator(use_llm_judge=True, provider=provider)
        record = _numeric_record()
        result = _result(claims=[{"text": "TCS revenue was 100.0.", "evidence_ids": ["ev-1"]}],
                         evidence=[{"evidence_id": "ev-1", "type": "financial_fact"}])
        r = ev.score(record, result)
        self.assertEqual(r["verdict"], "pass")

    def test_llm_judge_never_overrides_a_layer1_fail(self):
        # a disagreeing-but-"correct":true judge must not rescue a real rule-based failure
        # -- numeric/factual truth never comes from the LLM in this project.
        provider = _FakeProvider(response_text=json.dumps({"correct": True, "reasoning": "looks fine to me"}))
        ev = LayeredCorrectnessEvaluator(use_llm_judge=True, provider=provider)
        record = _numeric_record(reference_value=999.0, tolerance_pct=1.0)
        result = _result(value=100.0)
        r = ev.score(record, result)
        self.assertEqual(r["verdict"], "fail")

    def test_llm_judge_not_invoked_when_disabled_even_with_a_provider(self):
        provider = _FakeProvider(response_text=json.dumps({"correct": True}))
        ev = LayeredCorrectnessEvaluator(use_llm_judge=False, provider=provider)
        ev.score(_numeric_record(), _result())
        self.assertEqual(provider.calls, [])

    def test_citation_metrics_present_with_no_gold_are_none_not_zero(self):
        ev = LayeredCorrectnessEvaluator()
        r = ev.score(_numeric_record(), _result())
        citation = r["metrics"]["layer2_citation"]
        self.assertIsNone(citation["precision"])
        self.assertIsNone(citation["recall"])


if __name__ == "__main__":
    unittest.main()
