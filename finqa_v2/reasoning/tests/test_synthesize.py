"""render_workspace / build_prompt / parse_synthesis / deterministic_answer."""
from __future__ import annotations

import json
import unittest

from finqa_v2.evidence import EvidenceSet
from finqa_v2.evidence.models import Citation, Evidence, EvidenceType
from finqa_v2.planner.models import Intent, QueryPlan
from finqa_v2.reasoning.synthesize import (
    build_prompt,
    deterministic_answer,
    parse_synthesis,
    render_workspace,
)


def _ws():
    w = EvidenceSet()
    w.add(Evidence(evidence_id="ev-roe", type=EvidenceType.RATIO, company="TCS", metric="roe",
                   period="FY2026", value=25.0, unit="pct", formula="net_profit / total_equity * 100",
                   confidence=0.9))
    w.add(Evidence(evidence_id="ev-np", type=EvidenceType.FINANCIAL_FACT, company="TCS",
                   metric="net_profit", period="FY2026", value=150.0, unit="INR", confidence=0.98))
    w.add(Evidence(evidence_id="ev-doc", type=EvidenceType.DOCUMENT, company="TCS", document_id=5,
                   page=4, section="notes", text="Management noted pricing pressure in select accounts.",
                   confidence=0.5, citation=Citation("c1", "document", title="TCS Results", page=4, page_end=4)))
    return w


_PLAN = QueryPlan(question="What was TCS ROE in FY2026?", intent=Intent.NUMERIC_FACT,
                  companies=["TCS"], metrics=["roe"], periods=["FY2026"], tools=["get_ratio"])


class TestRender(unittest.TestCase):
    def test_render_contains_ids_and_sections(self):
        txt = render_workspace(_ws())
        self.assertIn("FACTS & CALCULATIONS:", txt)
        self.assertIn("(ev-roe)", txt)
        self.assertIn("[net_profit / total_equity * 100]", txt)
        self.assertIn("DOCUMENT PASSAGES:", txt)
        self.assertIn("(ev-doc)", txt)
        self.assertIn("pricing pressure", txt)

    def test_build_prompt(self):
        p = build_prompt("What was TCS ROE in FY2026?", _PLAN, _ws())
        self.assertIn("Planned intent: numeric_fact", p)
        self.assertIn("ev-roe", p)
        self.assertIn('"answer"', p)


class TestParse(unittest.TestCase):
    IDS = {"ev-roe", "ev-np", "ev-doc"}

    def test_good(self):
        raw = json.dumps({
            "answer": "TCS ROE in FY2026 was 25.0%.",
            "key_findings": ["ROE 25%"],
            "claims": [{"text": "TCS ROE was 25.0%", "kind": "numeric", "evidence_ids": ["ev-roe", "ev-np"]}],
            "limitations": [],
        })
        d = parse_synthesis(raw, self.IDS)
        self.assertEqual(d["answer"], "TCS ROE in FY2026 was 25.0%.")
        self.assertEqual(d["claims"][0]["evidence_ids"], ["ev-roe", "ev-np"])

    def test_filters_bogus_evidence_ids_and_kind(self):
        raw = json.dumps({"answer": "x", "claims": [
            {"text": "c", "kind": "wizardry", "evidence_ids": ["ev-roe", "ev-FAKE"]}]})
        d = parse_synthesis(raw, self.IDS)
        self.assertEqual(d["claims"][0]["evidence_ids"], ["ev-roe"])
        self.assertEqual(d["claims"][0]["kind"], "qualitative")

    def test_prose_wrapped_json(self):
        raw = "Here you go:\n{\"answer\": \"ok\", \"claims\": []}\nThanks"
        self.assertEqual(parse_synthesis(raw, self.IDS)["answer"], "ok")

    def test_bad(self):
        self.assertIsNone(parse_synthesis("no json", self.IDS))
        self.assertIsNone(parse_synthesis(json.dumps({"answer": ""}), self.IDS))
        self.assertIsNone(parse_synthesis(json.dumps(["a"]), self.IDS))


class TestDeterministic(unittest.TestCase):
    def test_stitches_facts(self):
        d = deterministic_answer("What was TCS ROE?", _PLAN, _ws())
        self.assertIn("25.00 pct", d["answer"])
        self.assertTrue(all(c["kind"] == "numeric" for c in d["claims"]))
        self.assertTrue(any("no llm synthesis" in l.lower() for l in d["limitations"]))

    def test_causal_without_docs_flags_gap(self):
        w = EvidenceSet()
        w.add(Evidence(evidence_id="ev-g", type=EvidenceType.GROWTH, company="TCS",
                       metric="revenue_yoy", period="FY2025 -> FY2026", value=4.5, unit="pct",
                       confidence=0.9))
        plan = QueryPlan(question="Why did TCS revenue barely grow?", intent=Intent.CAUSAL,
                         companies=["TCS"], metrics=["revenue"], tools=["get_growth", "search_documents"])
        d = deterministic_answer(plan.question, plan, w)
        self.assertTrue(any("cause is not established" in l for l in d["limitations"]))

    def test_no_evidence(self):
        d = deterministic_answer("huh?", QueryPlan(question="huh?", intent=Intent.UNKNOWN), EvidenceSet())
        self.assertIn("not sufficient", d["answer"])
        self.assertEqual(d["claims"], [])


if __name__ == "__main__":
    unittest.main()
