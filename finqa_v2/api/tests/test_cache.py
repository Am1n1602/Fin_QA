"""Tests for the Phase 27 in-process answer cache. See docs/file-guide.md."""
from __future__ import annotations

import unittest

from finqa_v2.api.cache import LruCache


class TestLruCache(unittest.TestCase):
    def test_second_call_with_the_same_key_does_not_recompute(self):
        cache = LruCache("test")
        calls = []

        def compute():
            calls.append(1)
            return "answer"

        self.assertEqual(cache.get_or_compute(("q1", True), compute), "answer")
        self.assertEqual(cache.get_or_compute(("q1", True), compute), "answer")
        self.assertEqual(len(calls), 1)

    def test_different_keys_each_recompute_independently(self):
        cache = LruCache("test")
        calls = []

        def compute():
            calls.append(1)
            return len(calls)

        self.assertEqual(cache.get_or_compute(("q1", True), compute), 1)
        self.assertEqual(cache.get_or_compute(("q1", False), compute), 2)
        self.assertEqual(cache.get_or_compute(("q2", True), compute), 3)
        self.assertEqual(len(calls), 3)

    def test_lru_eviction_drops_the_least_recently_used_entry(self):
        cache = LruCache("test", maxsize=2)
        cache.get_or_compute("a", lambda: "A")
        cache.get_or_compute("b", lambda: "B")
        cache.get_or_compute("a", lambda: "A-recomputed")  # touch "a" again -> LRU order [b, a]
        cache.get_or_compute("c", lambda: "C")  # over capacity -> evicts "b" -> [a, c]

        calls = []
        cache.get_or_compute("b", lambda: calls.append(1) or "B-again")
        self.assertEqual(calls, [1])  # "b" was evicted -> recomputed

        calls = []
        cache.get_or_compute("c", lambda: calls.append(1) or "unused")
        self.assertEqual(calls, [])  # "c" is still cached


if __name__ == "__main__":
    unittest.main()
