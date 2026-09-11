"""End-to-end checks against the real finqa_v2.db via fastapi.testclient.TestClient (no
network, no uvicorn -- ASGI in-process). Deterministic only (use_llm=False everywhere) so
these spend no tokens. Gated: skipped if the DB isn't built.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "database" / "data" / "finqa_v2.db"


def _has_uri_key(payload: dict) -> bool:
    return '"uri":' in json.dumps(payload)


@unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
class DeterministicEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from finqa_v2.api.main import app

        cls._app = app
        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["db_ready"])
        self.assertTrue(r.json()["engine_ready"])

    def test_metrics_endpoint_records_real_requests(self):
        self.client.get("/api/v2/companies/TCS/ratios?ratio=roe&period=FY2026")
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        body = r.text
        # path is the route TEMPLATE, not the real ticker -- confirms no per-company cardinality blowup.
        self.assertIn('path="/api/v2/companies/{ticker}/ratios"', body)
        self.assertNotIn('path="/api/v2/companies/TCS/ratios"', body)
        self.assertIn("finqa_tool_calls_total", body)

    def test_companies_list_get_peers(self):
        r = self.client.get("/api/v2/companies")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.json()["count"], 40)

        r = self.client.get("/api/v2/companies/TCS")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ticker"], "TCS")

        r = self.client.get("/api/v2/companies/TCS/peers?limit=3")
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()["peers"]), 3)

    def test_unknown_company_is_404(self):
        # routed through the generic tool bridge (deps.call_tool), which maps any
        # LookupError to a generic "not_found" -- it doesn't know the entity type.
        r = self.client.get("/api/v2/companies/ZZZNOTREAL")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"], "not_found")

    def test_financials_ratios_growth(self):
        r = self.client.get("/api/v2/companies/TCS/financials?metric=revenue&period=FY2026")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["value"], 0)

        r = self.client.get("/api/v2/companies/TCS/ratios?ratio=roe&period=FY2026")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()["value"])

        r = self.client.get("/api/v2/companies/TCS/ratios/decompose?metric=roe")
        self.assertEqual(r.status_code, 200)

        r = self.client.get("/api/v2/companies/TCS/growth?metric=revenue")
        self.assertEqual(r.status_code, 200)

        r = self.client.get("/api/v2/companies/TCS/growth/cagr?metric=revenue")
        self.assertEqual(r.status_code, 200)

    def test_segments_and_segment_growth(self):
        r = self.client.get("/api/v2/companies/RELIANCE/segments")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

        r = self.client.get("/api/v2/companies/RELIANCE/segments/growth")
        self.assertEqual(r.status_code, 200)
        self.assertIn("rows", r.json())

    def test_rankings(self):
        r = self.client.get("/api/v2/rankings?metric=roe&tickers=TCS,INFY,HCLTECH")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["results"]), 3)

    def test_search_and_documents_no_uri_leak(self):
        r = self.client.get("/api/v2/search?q=risk factors&company=TCS&k=3")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(_has_uri_key(r.json()))

        r = self.client.get("/api/v2/companies/TCS/documents/segment_information?limit=3")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(_has_uri_key(r.json()))

    def test_qa_deterministic_no_uri_leak(self):
        r = self.client.post("/api/v2/qa", json={"question": "What was TCS revenue in FY2026?",
                                                  "use_llm": False})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("2,670,210,000,000", body["response"]["answer"].replace(" ", ""))
        self.assertFalse(_has_uri_key(body))
        self.assertIn("claim_graph", body)

    def test_research_deterministic_no_uri_leak(self):
        r = self.client.get("/api/v2/companies/HCLTECH/research?use_llm=false")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(_has_uri_key(r.json()))

    def test_research_unknown_company_uses_the_specific_error_code(self):
        # /research resolves the company directly (deps.resolve_company), so it gets the
        # more specific company_not_found code, unlike the generic tool-bridge path above.
        r = self.client.get("/api/v2/companies/ZZZNOTREAL/research")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"], "company_not_found")

    def test_claim_graph_is_reachable_only_in_the_api(self):
        r = self.client.post("/api/v2/qa", json={"question": "Why did HCLTECH profitability decline?",
                                                  "use_llm": False})
        self.assertEqual(r.status_code, 200)
        cg = r.json()["claim_graph"]
        node_ids = {n["id"] for n in cg["graph"]["nodes"]}
        # every evidence/source node in the (reachable-only) export must be cited by a claim
        cited = set()
        for cl in cg["claims"]:
            cited.update(e["evidence_id"] for e in cl["evidence"])
        ev_nodes = {n["id"] for n in cg["graph"]["nodes"] if n["type"] == "evidence"}
        self.assertTrue(ev_nodes <= node_ids)


@unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
class RateLimitAndAuth(unittest.TestCase):
    """require_api_key / rate_limit_qa read os.environ directly (not a cached config
    constant), so patching the env here takes effect immediately -- no reload needed."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from finqa_v2.api.main import app

        cls._ctx = TestClient(app)
        cls.client = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def test_qa_rate_limit_returns_429_eventually(self):
        import os

        with mock.patch.dict(os.environ, {"FINQA_V2_QA_RATE_LIMIT": "2"}):
            statuses = [
                self.client.post("/api/v2/qa",
                                 json={"question": "What was TCS revenue in FY2026?", "use_llm": False}
                                 ).status_code
                for _ in range(4)
            ]
        self.assertIn(429, statuses)

    def test_api_key_required_when_configured(self):
        import os

        with mock.patch.dict(os.environ, {"FINQA_V2_API_KEY": "secret123"}):
            r = self.client.post("/api/v2/qa", json={"question": "hi", "use_llm": False})
            self.assertEqual(r.status_code, 401)
            r = self.client.post("/api/v2/qa",
                                 json={"question": "What was TCS revenue in FY2026?", "use_llm": False},
                                 headers={"X-API-Key": "secret123"})
            self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
