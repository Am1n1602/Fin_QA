"""Environment-variable configuration for the v2 API (mirrors v1's api/config.py style:
plain module constants, no config framework). See docs/file-guide.md.

    FINQA_V2_DB_PATH              -- path to finqa_v2.db (default: SqliteRepositories default)
    FINQA_V2_API_HOST             -- default 0.0.0.0
    FINQA_V2_API_PORT             -- default 8010 (distinct from v1's finqa-api on 8000)
    FINQA_V2_API_CORS_ORIGINS     -- comma-separated origins, "*" for all (dev only)
    FINQA_V2_API_KEY              -- if set, every request (except /health, /metrics) must
                                     echo it in X-API-Key.
    FINQA_V2_RATE_LIMIT           -- max calls per client IP per rolling 60s window,
                                     enforced on every route except /health and /metrics
                                     (default 120). 0 or negative disables it.
    FINQA_V2_QA_RATE_LIMIT        -- a second, much stricter limit that ONLY /qa and
                                     /research additionally apply on top of the general
                                     one above, since an LLM call there has real cost/
                                     latency (default 10). 0 or negative disables it.
    FINQA_V2_NO_RETRIEVER         -- "1" to start without wiring BM25/vector (search &
                                     qa's document evidence degrade; deterministic
                                     endpoints unaffected).
    FINQA_V2_LOG_JSON             -- "1" for one JSON log line per event (production);
                                     default is plain text (easier in a dev terminal).
    FINQA_V2_EVAL_BASELINE_PATH   -- pinned regression-gate baseline JSON to surface via
                                     /metrics' eval-monitoring gauges (default: the
                                     deterministic_v2.json this repo ships).
"""
from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "database" / "data"

HOST = os.environ.get("FINQA_V2_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("FINQA_V2_API_PORT", "8010"))

_raw_origins = os.environ.get("FINQA_V2_API_CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

# NB: FINQA_V2_API_KEY, FINQA_V2_RATE_LIMIT, and FINQA_V2_QA_RATE_LIMIT are read directly
# from os.environ inside deps.check_api_key / deps.check_general_rate_limit /
# deps.rate_limit_qa (not cached here as constants) so a test can patch os.environ and
# see the effect immediately, with no module-reload dance.
NO_RETRIEVER = os.environ.get("FINQA_V2_NO_RETRIEVER") == "1"
DB_PATH = os.environ.get("FINQA_V2_DB_PATH") or None
BM25_PATH = Path(os.environ.get("FINQA_V2_BM25_PATH") or (_DATA / "finqa_v2_bm25.pkl"))
VECTOR_DIR = Path(os.environ.get("FINQA_V2_VECTOR_DIR") or (_DATA / "finqa_v2_vec"))
EVAL_BASELINE_PATH = Path(os.environ.get("FINQA_V2_EVAL_BASELINE_PATH")
                          or (_ROOT / "evaluation" / "regression" / "baselines" / "deterministic_v2.json"))
