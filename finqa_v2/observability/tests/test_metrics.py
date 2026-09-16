"""finqa_v2/observability/metrics.py -- each recorder writes to the shared, module-level
REGISTRY (mirrors real usage: one process, one registry), so assertions check the DELTA
around a call rather than an absolute value other test cases may have already changed.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from finqa_v2.observability import metrics as m

_SKIP = not m._AVAILABLE
_SKIP_REASON = "prometheus_client not installed -- pip install -e '.[observability]'"


def _value(name: str, labels: dict) -> float:
    return m.REGISTRY.get_sample_value(name, labels) or 0.0


def _count(name: str, labels: dict) -> float:
    # Counters/Histograms expose their count under "<name>_total" / "<name>_count".
    return m.REGISTRY.get_sample_value(f"{name}_total", labels) \
        or m.REGISTRY.get_sample_value(f"{name}_count", labels) or 0.0


@unittest.skipIf(_SKIP, _SKIP_REASON)
class TestRecorders(unittest.TestCase):
    def test_record_tool_call_ok_and_error(self):
        before_ok = _count("finqa_tool_calls", {"tool": "get_metric", "status": "ok"})
        before_err = _count("finqa_tool_calls", {"tool": "get_metric", "status": "error"})
        m.record_tool_call("get_metric", True, 12.5)
        m.record_tool_call("get_metric", False, 3.0)
        self.assertEqual(_count("finqa_tool_calls", {"tool": "get_metric", "status": "ok"}), before_ok + 1)
        self.assertEqual(_count("finqa_tool_calls", {"tool": "get_metric", "status": "error"}), before_err + 1)

    def test_record_llm_usage_groq_no_cost(self):
        before_req = _count("finqa_llm_requests", {"provider": "groq"})
        before_tok = _value("finqa_llm_tokens_total", {"provider": "groq", "kind": "prompt"})
        m.record_llm_usage("groq", prompt_tokens=100, completion_tokens=50)
        self.assertEqual(_count("finqa_llm_requests", {"provider": "groq"}), before_req + 1)
        self.assertEqual(_value("finqa_llm_tokens_total", {"provider": "groq", "kind": "prompt"}), before_tok + 100)
        # Groq is free-tier: no cost_usd passed -> the cost counter must not move.
        self.assertEqual(_value("finqa_llm_cost_usd_total", {"provider": "groq"}), 0.0)

    def test_record_llm_usage_anthropic_with_cost(self):
        before_cost = _value("finqa_llm_cost_usd_total", {"provider": "anthropic"})
        m.record_llm_usage("anthropic", prompt_tokens=1000, completion_tokens=500, cost_usd=0.0123)
        self.assertAlmostEqual(
            _value("finqa_llm_cost_usd_total", {"provider": "anthropic"}), before_cost + 0.0123, places=6)

    def test_record_verification(self):
        before = _count("finqa_verification_status", {"status": "passed"})
        m.record_verification("passed")
        self.assertEqual(_count("finqa_verification_status", {"status": "passed"}), before + 1)

    def test_record_http_request(self):
        before = _count("finqa_http_requests", {"method": "GET", "path": "/health", "status": "200"})
        m.record_http_request("GET", "/health", 200, 0.01)
        self.assertEqual(_count("finqa_http_requests", {"method": "GET", "path": "/health", "status": "200"}), before + 1)

    def test_render_latest_contains_known_metrics(self):
        m.record_tool_call("get_ratio", True, 1.0)
        out = m.render_latest()
        self.assertIn(b"finqa_tool_calls_total", out)


@unittest.skipIf(_SKIP, _SKIP_REASON)
class TestEvalBaselineGauges(unittest.TestCase):
    def test_missing_file_returns_empty_and_does_not_raise(self):
        result = m.refresh_eval_baseline_gauges(Path("/nonexistent/does-not-exist.json"))
        self.assertEqual(result, {})

    def test_real_shaped_baseline_sets_expected_gauges(self):
        report = {
            "label": "det-v2", "git_commit": "abcdef1234567890", "generated_at": "2026-01-01T00:00:00Z",
            "aggregates": {
                "numerical": {"accuracy": 1.0, "checked": 23},
                "groundedness": {"verdict": {"accuracy": 0.97}},
                "citation": {"mean_precision": 0.8, "mean_recall": 0.6},
                "abstention": {"accuracy": 0.95},
            },
        }
        with TemporaryDirectory() as d:
            path = Path(d) / "baseline.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            values = m.refresh_eval_baseline_gauges(path)

        self.assertEqual(values["numerical"], 1.0)
        self.assertEqual(values["groundedness"], 0.97)
        self.assertEqual(values["citation_precision"], 0.8)
        self.assertEqual(values["citation_recall"], 0.6)
        self.assertEqual(values["abstention"], 0.95)
        self.assertEqual(_value("finqa_eval_baseline_accuracy", {"metric": "numerical"}), 1.0)

    def test_malformed_json_returns_empty(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text("{not valid json", encoding="utf-8")
            self.assertEqual(m.refresh_eval_baseline_gauges(path), {})


if __name__ == "__main__":
    unittest.main()
