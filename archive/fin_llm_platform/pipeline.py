from __future__ import annotations

import sys

from ._paths import ORCHESTRATOR_DIR, check_layout


def main() -> int:
    problems = check_layout()
    if problems:
        for p in problems:
            print(f"finqa-pipeline: {p}", file=sys.stderr)
        print(
            "finqa-pipeline: this console command expects to run from an editable install "
            "(`pip install -e .` from the project root) with all sibling project "
            "folders still present alongside fin_llm_platform/ -- see MANUAL.md.",
            file=sys.stderr,
        )
        return 1

    sys.path.insert(0, str(ORCHESTRATOR_DIR))
    from run_nifty50_pipeline import main as pipeline_main  # noqa: PLC0415 -- see module docstring

    return pipeline_main()


if __name__ == "__main__":
    raise SystemExit(main())