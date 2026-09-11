"""Bounded in-process cache for /qa and /research (Phase 27, §27 caching). Measured
justification: an LLM-backed answer costs seconds (Phase 20/21 baselines), while every
other layer (engine reads, retrieval) is sub-100ms -- so caching the rendered answer is
where repeat-question latency/cost actually goes. The dataset is static for the lifetime
of a running container (engine/retriever/DB connection are all built once at startup,
see main.py's lifespan) so an identical (question, use_llm) or (ticker, use_llm) pair
always recomputes the exact same answer -- caching it is exact, not an approximation,
and a real data update requires a container restart anyway, which naturally clears this.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any, Callable, Hashable

from finqa_v2.observability import record_cache_event


class LruCache:
    def __init__(self, name: str, maxsize: int = 256) -> None:
        self._name = name
        self._maxsize = maxsize
        self._lock = Lock()
        self._data: "OrderedDict[Hashable, Any]" = OrderedDict()

    def get_or_compute(self, key: Hashable, compute: Callable[[], Any]) -> Any:
        # No per-key lock: two concurrent requests for the SAME uncached key can both
        # run `compute()` and each pay the full LLM cost once -- an accepted duplicate
        # at this traffic scale, not a thundering-herd problem worth a lock-per-key.
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                record_cache_event(self._name, hit=True)
                return self._data[key]
        value = compute()
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)
        record_cache_event(self._name, hit=False)
        return value
