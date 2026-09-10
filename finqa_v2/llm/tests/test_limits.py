"""RateBudget: session cap / TPD raise; RPM / TPM sleep; sliding-window prune; usage."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from finqa_v2.llm.limits import LLMBudgetExceededError, RateBudget, estimate_tokens


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, secs: float) -> None:
        self.slept.append(secs)
        self.t += secs


def _budget(**kw) -> tuple[RateBudget, FakeClock]:
    fc = FakeClock()
    b = RateBudget(clock=fc.now, sleep=fc.sleep, **kw)
    return b, fc


class TestEstimate(unittest.TestCase):
    def test_estimate(self):
        self.assertEqual(estimate_tokens("a" * 400, "b" * 400, 500), 200 + 500)
        self.assertEqual(estimate_tokens("", None, 100), 100)


class TestHardCaps(unittest.TestCase):
    def test_session_request_cap_raises(self):
        b, _ = _budget(max_requests=2, tpd_limit=10_000)
        for _ in range(2):
            b.check_and_reserve(10)
            b.record(5, 5)
        with self.assertRaises(LLMBudgetExceededError):
            b.check_and_reserve(10)

    def test_tpd_cap_raises_before_call(self):
        b, _ = _budget(max_requests=100, tpd_limit=1_000)
        b.check_and_reserve(600)
        b.record(300, 300)                      # 600 used
        with self.assertRaises(LLMBudgetExceededError):
            b.check_and_reserve(600)            # 600 + 600 > 1000


class TestSlidingWindow(unittest.TestCase):
    def test_rpm_sleeps_then_proceeds(self):
        b, fc = _budget(max_requests=100, rpm_limit=3, tpm_limit=10 ** 9)
        for _ in range(3):
            b.check_and_reserve(1)
            b.record(1, 1)
        b.check_and_reserve(1)                  # window full -> must sleep ~60s
        self.assertTrue(fc.slept)
        self.assertGreater(fc.slept[-1], 55)

    def test_tpm_sleeps_when_window_tokens_exceed(self):
        b, fc = _budget(max_requests=100, rpm_limit=100, tpm_limit=1_000)
        b.check_and_reserve(700)
        b.record(350, 350)                      # 700 in window
        b.check_and_reserve(700)               # 700 + 700 > 1000 -> sleep
        self.assertTrue(fc.slept)

    def test_window_prunes_after_60s(self):
        b, fc = _budget(max_requests=100, rpm_limit=2, tpm_limit=10 ** 9)
        b.check_and_reserve(1); b.record(1, 1)
        b.check_and_reserve(1); b.record(1, 1)
        fc.t += 61                              # both entries now stale
        b.check_and_reserve(1)                 # window pruned -> no sleep
        self.assertEqual(fc.slept, [])


class TestUsageAndEnv(unittest.TestCase):
    def test_usage_dict(self):
        b, _ = _budget(max_requests=5, tpd_limit=1_000)
        b.check_and_reserve(20); b.record(30, 10)
        u = b.usage
        self.assertEqual(u["total_tokens"], 40)
        self.assertEqual(u["requests_made"], 1)
        self.assertEqual(u["requests_remaining"], 4)
        self.assertEqual(u["tpd_remaining"], 960)

    def test_from_env_overrides(self):
        with patch.dict("os.environ", {"FINQA_LLM_MAX_REQUESTS": "7", "FINQA_LLM_TPD": "12345"}):
            b = RateBudget.from_env()
        self.assertEqual(b.max_requests, 7)
        self.assertEqual(b.tpd_limit, 12345)

    def test_from_env_defaults_are_conservative(self):
        b = RateBudget.from_env()
        self.assertLessEqual(b.tpm_limit, 8_000)
        self.assertLessEqual(b.tpd_limit, 200_000)
        self.assertLessEqual(b.rpm_limit, 30)


if __name__ == "__main__":
    unittest.main()
