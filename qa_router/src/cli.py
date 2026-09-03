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

from src.bridges.analysis_bridge import AnalysisBridge
from src.bridges.rag_bridge import RagBridge
from src.config import DATA_ANALYSIS_DIR, DB_PATH, DEVICE, EMBEDDING_MODEL_NAME, RAG_DIR, RAG_INDEX_DIR, \
    RERANK_MODEL_NAME
from src.qa import answer_question


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


def main() -> None:
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

    analysis_bridge = AnalysisBridge(db_path=args.db_path, data_analysis_dir=args.data_analysis_dir)
    rag_bridge = RagBridge(db_path=args.db_path, rag_dir=args.rag_dir, index_dir=args.index_dir,
                            model_name=args.model_name, rerank_model=args.rerank_model, device=args.device)

    try:
        if args.question:
            result = answer_question(args.question, db_path=args.db_path,
                                      analysis_bridge=analysis_bridge, rag_bridge=rag_bridge)
            _print_result(result, args.json)
            return

        print("Stage 10 QA Router -- interactive mode. Ctrl-D or 'quit' to exit.")
        while True:
            try:
                question = input("\n> ").strip()
            except EOFError:
                break
            if not question or question.lower() in ("quit", "exit"):
                break
            result = answer_question(question, db_path=args.db_path,
                                      analysis_bridge=analysis_bridge, rag_bridge=rag_bridge)
            _print_result(result, args.json)
    finally:
        analysis_bridge.close()
        rag_bridge.close()


if __name__ == "__main__":
    main()
