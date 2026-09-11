"""LLM provider: NullProvider raises, GroqProvider structure, provider_from_env, and an
optional real call gated behind FINQA_LLM_TESTS=1."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from finqa_v2.llm import LLMBudgetExceededError, LLMError, NullProvider, provider_from_env
from finqa_v2.llm.provider import AnthropicProvider, GroqProvider, _read_env_key, anthropic_provider_from_env


class TestProviders(unittest.TestCase):
    def test_null_provider_raises(self):
        with self.assertRaises(LLMError):
            NullProvider().complete("hi")

    def test_groq_requires_key(self):
        # no explicit key AND nothing in env/.env -> raise
        with patch("finqa_v2.llm.provider._read_env_key", return_value=None):
            with self.assertRaises(LLMError):
                GroqProvider(api_key="")
            self.assertEqual(provider_from_env().name, "null")

    def test_groq_holds_config(self):
        p = GroqProvider(api_key="sk-test", model="m")
        self.assertEqual(p.name, "groq")
        self.assertEqual(p.model, "m")
        self.assertEqual(p.api_key, "sk-test")
        self.assertEqual(p.usage["requests_made"], 0)          # budget attached by default

    def test_disabled_env_forces_null(self):
        with patch.dict("os.environ", {"FINQA_LLM_DISABLED": "1"}):
            self.assertEqual(provider_from_env().name, "null")

    def test_shared_budget(self):
        from finqa_v2.llm import RateBudget

        b = RateBudget(max_requests=3)
        p = GroqProvider(api_key="x", budget=b)
        self.assertIs(p.budget, b)

    def test_from_env_returns_a_provider(self):
        p = provider_from_env()
        self.assertIn(p.name, ("groq", "null"))

    def test_runtime_checkable(self):
        from finqa_v2.llm.provider import LLMProvider

        self.assertIsInstance(NullProvider(), LLMProvider)
        self.assertIsInstance(GroqProvider(api_key="x"), LLMProvider)


class _FakeResp:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class TestBudgetWiring(unittest.TestCase):
    def _provider(self, **bkw):
        from finqa_v2.llm import RateBudget

        return GroqProvider(api_key="x", budget=RateBudget(clock=lambda: 0.0, sleep=lambda s: None, **bkw))

    def test_records_usage_from_response(self):
        p = self._provider(max_requests=10, tpd_limit=10_000)
        ok = _FakeResp(200, {"choices": [{"message": {"content": "hi"}}],
                             "usage": {"prompt_tokens": 40, "completion_tokens": 8}})
        with patch("requests.post", return_value=ok):
            self.assertEqual(p.complete("hello", max_tokens=16), "hi")
        self.assertEqual(p.usage["total_tokens"], 48)
        self.assertEqual(p.usage["requests_made"], 1)

    def test_session_cap_blocks_before_http(self):
        p = self._provider(max_requests=1, tpd_limit=10_000)
        ok = _FakeResp(200, {"choices": [{"message": {"content": "x"}}], "usage": {}})
        with patch("requests.post", return_value=ok) as post:
            p.complete("one", max_tokens=8)
            with self.assertRaises(LLMBudgetExceededError):
                p.complete("two", max_tokens=8)
            self.assertEqual(post.call_count, 1)          # 2nd call never hit the network

    def test_429_retries_then_raises(self):
        p = self._provider(max_requests=10, tpd_limit=10_000)
        r429 = _FakeResp(429, headers={"retry-after": "1"}, text="rate limited")
        with patch("requests.post", return_value=r429) as post:
            with self.assertRaises(LLMBudgetExceededError):
                p.complete("hi", max_tokens=8)
            self.assertEqual(post.call_count, 2)          # 1 try + 1 retry (max_retries=1)


@unittest.skipUnless(os.environ.get("FINQA_LLM_TESTS") == "1", "set FINQA_LLM_TESTS=1 (spends tokens)")
class TestRealGroq(unittest.TestCase):
    def test_json_completion(self):
        import json

        self.assertIsNotNone(_read_env_key())
        p = GroqProvider()
        out = p.complete('Return the JSON object {"pong": true}. JSON only.',
                         json_object=True, max_tokens=20)
        self.assertIn("pong", json.loads(out))


class TestAnthropicProvider(unittest.TestCase):
    def test_requires_key(self):
        with patch("finqa_v2.llm.provider._read_env_key", return_value=None):
            with self.assertRaises(LLMError):
                AnthropicProvider(api_key="")
            self.assertEqual(anthropic_provider_from_env().name, "null")

    def test_holds_config(self):
        p = AnthropicProvider(api_key="sk-ant-test", model="claude-sonnet-5")
        self.assertEqual(p.name, "anthropic")
        self.assertEqual(p.model, "claude-sonnet-5")
        self.assertEqual(p.usage["requests_made"], 0)          # CostBudget attached by default

    def test_disabled_env_forces_null(self):
        with patch.dict("os.environ", {"FINQA_LLM_DISABLED": "1"}):
            self.assertEqual(anthropic_provider_from_env().name, "null")

    def test_shared_cost_budget(self):
        from finqa_v2.llm import CostBudget

        b = CostBudget(max_cost_usd=1.0)
        p = AnthropicProvider(api_key="x", budget=b)
        self.assertIs(p.budget, b)

    def test_runtime_checkable(self):
        from finqa_v2.llm.provider import LLMProvider

        self.assertIsInstance(AnthropicProvider(api_key="x"), LLMProvider)

    def _provider(self, **bkw):
        from finqa_v2.llm import CostBudget

        return AnthropicProvider(api_key="x", model="claude-sonnet-5",
                                 budget=CostBudget(pricing={"claude-sonnet-5": (2.0, 10.0)}, **bkw))

    def test_records_cost_from_response(self):
        p = self._provider(max_cost_usd=1.0)
        ok = _FakeResp(200, {"content": [{"type": "text", "text": "hi"}],
                             "usage": {"input_tokens": 1000, "output_tokens": 500}})
        with patch("requests.post", return_value=ok):
            self.assertEqual(p.complete("hello", max_tokens=16), "hi")
        # 1000/1e6*2 + 500/1e6*10 = 0.002 + 0.005 = 0.007
        self.assertAlmostEqual(p.usage["spent_usd"], 0.007)
        self.assertEqual(p.usage["requests_made"], 1)

    def test_cost_cap_blocks_before_http(self):
        p = self._provider(max_cost_usd=0.0001)   # far below even one small call
        ok = _FakeResp(200, {"content": [{"type": "text", "text": "x"}], "usage": {}})
        with patch("requests.post", return_value=ok) as post:
            with self.assertRaises(LLMBudgetExceededError):
                p.complete("a" * 4000, max_tokens=500)
            post.assert_not_called()

    def test_json_object_nudges_system_prompt(self):
        p = self._provider(max_cost_usd=1.0)
        ok = _FakeResp(200, {"content": [{"type": "text", "text": "{}"}], "usage": {}})
        with patch("requests.post", return_value=ok) as post:
            p.complete("hi", system="be terse", json_object=True, max_tokens=8)
        self.assertIn("JSON object only", post.call_args.kwargs["json"]["system"])

    def test_429_retries_then_raises(self):
        p = self._provider(max_cost_usd=1.0, requests_made=0)
        r429 = _FakeResp(429, headers={"retry-after": "0"}, text="rate limited")
        with patch("requests.post", return_value=r429) as post, patch("time.sleep"):
            with self.assertRaises(LLMBudgetExceededError):
                p.complete("hi", max_tokens=8)
        self.assertEqual(post.call_count, 3)          # 1 try + 2 retries (max_retries=2)


@unittest.skipUnless(os.environ.get("FINQA_LLM_TESTS") == "1", "set FINQA_LLM_TESTS=1 (spends real $)")
class TestRealAnthropic(unittest.TestCase):
    def test_json_completion(self):
        import json

        self.assertIsNotNone(_read_env_key("ANTHROPIC_API_KEY"))
        p = AnthropicProvider()
        out = p.complete('Return the JSON object {"pong": true}. JSON only.',
                         json_object=True, max_tokens=20)
        self.assertIn("pong", json.loads(out))


if __name__ == "__main__":
    unittest.main()
