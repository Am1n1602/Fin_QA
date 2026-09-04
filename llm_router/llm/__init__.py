"""
llm_router/llm -- Stage 11 Hybrid LLM layer (Ollama local + Cloud).

Deliberately named `llm`, NOT `src` -- unlike data_analysis/, database/,
and rag/, this package needs to be imported DIRECTLY into qa_router's
process (see qa_router/src/llm_integration.py). Those other three siblings
all use a top-level package literally named `src`, which is exactly why
importing two of them in one process corrupts sys.modules['src'] (see
SESSION_ADDENDUM_3.md's "core technical problem" section) and forced the
subprocess-worker bridge pattern (bridges/analysis_worker.py,
bridges/rag_worker.py). Naming this package `llm` instead of `src` sidesteps
that collision entirely -- there is nothing else in this project's process
space named `llm` -- so no subprocess is needed here. That's also
appropriate on the merits: unlike rag's embedding/cross-encoder models or
data_analysis's calculation modules, an HTTP client (Ollama) and a thin SDK
client (Anthropic) have no heavy state worth amortizing across a subprocess
boundary.
"""
