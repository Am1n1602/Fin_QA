"""
qa_router/src/cli.py

Stage 10 command-line entry point.

    cd qa_router
    python -m src.cli "What is TCS's ROE?"
    python -m src.cli                       # interactive REPL, reuses one
                                              # pair of bridges across questions
    python -m src.cli "..." --json           # raw JSON result instead of the
                                              # formatted summary
    python -m src.cli "..." --db-path ... --data-analysis-dir ... --rag-dir ...
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import traceback

from src.bridges.analysis_bridge import AnalysisBridge
from src.bridges.rag_bridge import RagBridge
from src.config import DATA_ANALYSIS_DIR, DB_PATH, DEVICE, EMBEDDING_MODEL_NAME, RAG_DIR, RAG_INDEX_DIR, \
    RERANK_MODEL_NAME
from src.qa import answer_question

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def _friendly_error(exc: BaseException) -> str:
    """Maps a caught exception to a short, actionable message. See the
    module-level comment above for why this exists."""
    if isinstance(exc, (ModuleNotFoundError, ImportError)):
        missing = getattr(exc, "name", None) or str(exc)
        return (
            f"Missing dependency ({missing}). This almost always means your virtual environment "
            f"isn't activated, or you're running from the wrong folder. Activate it first "
            f"(Windows: 'venv\\Scripts\\activate' from the project root; macOS/Linux: "
            f"'source venv/bin/activate'), then run this command again from inside the qa_router folder."
        )
    if isinstance(exc, RuntimeError) and "worker exited unexpectedly" in str(exc):
        return (
            f"A background worker process crashed while starting up ({exc}). Check the error just "
            f"above this one (printed directly by that process) -- a missing-package error there "
            f"usually means the virtual environment used to launch this command isn't the one with "
            f"all the project's dependencies installed."
        )
    if isinstance(exc, sqlite3.OperationalError):
        return (
            f"Could not open or read the database ({exc}). Check that --db-path points at a real, "
            f"unlocked financial_intelligence.db file, and that no other process (e.g. the "
            f"orchestrator) has it open at the same time."
        )
    if isinstance(exc, FileNotFoundError):
        return (
            f"A required file or folder is missing ({exc}). Check that --data-analysis-dir/--rag-dir/"
            f"--index-dir point at real, already-built locations -- this usually means the ingestion "
            f"pipeline hasn't been run yet for this data."
        )
    return f"Something went wrong ({type(exc).__name__}: {exc}). Full details were written to stderr."


def _print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return
    c = result["classification"]
    print(f"\n[intent: {result['intent']}  confidence: {c['confidence']}]")
    if c["companies"]:
        print(f"  companies: {c['companies']}")
    if c["metrics"]:
        print(f"  metrics:   {c['metrics']}")
    print(f"\n{result['answer']}\n")
    if result["warnings"]:
        print("Warnings:")
        for w in result["warnings"]:
            print(f"  - {w}")
    if result["sources"]:
        print(f"\nSources ({len(result['sources'])}):")
        for s in result["sources"][:10]:
            print(f"  - {s}")
        if len(result["sources"]) > 10:
            print(f"  ... and {len(result['sources']) - 10} more")


def _run(args: argparse.Namespace) -> int:
    analysis_bridge = AnalysisBridge(db_path=args.db_path, data_analysis_dir=args.data_analysis_dir)
    rag_bridge = RagBridge(db_path=args.db_path, rag_dir=args.rag_dir, index_dir=args.index_dir,
                            model_name=args.model_name, rerank_model=args.rerank_model, device=args.device)
    try:
        if args.question:
            result = answer_question(args.question, db_path=args.db_path,
                                      analysis_bridge=analysis_bridge, rag_bridge=rag_bridge)
            _print_result(result, args.json)
            return 0

        print("Stage 10 QA Router -- interactive mode. Ctrl-D or 'quit' to exit.")
        while True:
            try:
                question = input("\n> ").strip()
            except EOFError:
                break
            if not question or question.lower() in ("quit", "exit"):
                break
            try:
                result = answer_question(question, db_path=args.db_path,
                                          analysis_bridge=analysis_bridge, rag_bridge=rag_bridge)
                _print_result(result, args.json)
            except Exception as exc:  # noqa: BLE001 -- per-question isolation is the point, see above
                print(f"\n{_friendly_error(exc)}")
                traceback.print_exc(file=sys.stderr)
        return 0
    finally:
        analysis_bridge.close()
        rag_bridge.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--data-analysis-dir", default=str(DATA_ANALYSIS_DIR))
    parser.add_argument("--rag-dir", default=str(RAG_DIR))
    parser.add_argument("--index-dir", default=str(RAG_INDEX_DIR))
    parser.add_argument("--model-name", default=EMBEDDING_MODEL_NAME)
    parser.add_argument("--rerank-model", default=RERANK_MODEL_NAME)
    parser.add_argument("--device", default=DEVICE)
    parser.add_argument("--json", action="store_true", help="Print the full raw result as JSON")
    args = parser.parse_args()

    try:
        return _run(args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130  # conventional Unix exit code for a SIGINT-terminated process
    except Exception as exc:  # noqa: BLE001 -- this IS the last-resort boundary, see docstring above
        print(f"\n{_friendly_error(exc)}")
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())